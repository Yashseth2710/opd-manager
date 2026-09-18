"""Queries for appointments and their history.

Everything goes through the scoped repository, so another clinic's
appointment reads as absent rather than forbidden.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select

from app.models import Appointment, AppointmentEvent, Doctor, Patient, PatientAllergy
from app.models.appointment import RELEASED
from app.repositories.base import TenantScopedRepository


@dataclass(frozen=True)
class Listed:
    appointment: Appointment
    patient: Patient
    doctor: Doctor
    allergy_count: int


def allergy_count() -> ColumnElement[int]:
    return (
        select(func.count())
        .select_from(PatientAllergy)
        .where(PatientAllergy.patient_id == Patient.id)
        .correlate(Patient)
        .scalar_subquery()
    )


class AppointmentRepository(TenantScopedRepository[Appointment]):
    model = Appointment

    def _joined(self) -> Select[tuple[Appointment, Patient, Doctor, int]]:
        return (
            select(Appointment, Patient, Doctor, allergy_count())
            .join(Patient, Patient.id == Appointment.patient_id)
            .join(Doctor, Doctor.id == Appointment.doctor_id)
            .where(Appointment.organization_id == self.organization_id)
        )

    async def _rows(self, statement: Select[Any]) -> list[Listed]:
        result = await self.session.execute(statement)
        return [
            Listed(appointment=row[0], patient=row[1], doctor=row[2], allergy_count=row[3])
            for row in result.all()
        ]

    async def one(self, appointment_id: uuid.UUID, *, lock: bool = False) -> Listed | None:
        """One appointment, locked for the rest of the request when it is about
        to change: a cancel and a check-in landing together then take turns,
        and the second one sees what the first did."""
        statement = self._joined().where(Appointment.id == appointment_id)
        if lock:
            statement = statement.with_for_update(of=Appointment).execution_options(
                populate_existing=True
            )
        found = await self._rows(statement)
        return found[0] if found else None

    async def between(
        self,
        opens_at: dt.datetime,
        closes_at: dt.datetime,
        *,
        doctor_id: uuid.UUID | None = None,
    ) -> list[Listed]:
        """Everything starting inside a window, cancelled ones included: the
        desk needs to see that a slot was given up, not just that it is free."""
        statement = (
            self._joined()
            .where(Appointment.scheduled_start >= opens_at)
            .where(Appointment.scheduled_start < closes_at)
        )
        if doctor_id is not None:
            statement = statement.where(Appointment.doctor_id == doctor_id)
        return await self._rows(
            statement.order_by(
                Appointment.scheduled_start,
                Doctor.last_name,
                Doctor.first_name,
                # Two appointments at one time with two doctors of one name
                # still come back in the same order every time.
                Appointment.id,
            )
        )

    async def for_patient(
        self,
        patient_id: uuid.UUID,
        *,
        doctor_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[Listed]:
        statement = self._joined().where(Appointment.patient_id == patient_id)
        if doctor_id is not None:
            statement = statement.where(Appointment.doctor_id == doctor_id)
        return await self._rows(
            statement.order_by(Appointment.scheduled_start.desc(), Appointment.id.desc()).limit(
                limit
            )
        )

    async def held(
        self,
        doctor_id: uuid.UUID,
        opens_at: dt.datetime,
        closes_at: dt.datetime,
        *,
        ignoring: uuid.UUID | None = None,
    ) -> list[tuple[dt.datetime, dt.datetime]]:
        """The stretches of a doctor's day that bookings are sitting on."""
        statement = (
            select(Appointment.scheduled_start, Appointment.scheduled_end)
            .where(Appointment.organization_id == self.organization_id)
            .where(Appointment.doctor_id == doctor_id)
            .where(Appointment.status.not_in(RELEASED))
            .where(Appointment.scheduled_start < closes_at)
            .where(Appointment.scheduled_end > opens_at)
        )
        if ignoring is not None:
            statement = statement.where(Appointment.id != ignoring)
        result = await self.session.execute(statement)
        return [(row[0], row[1]) for row in result.all()]

    async def patient_clash(
        self,
        patient_id: uuid.UUID,
        starts: dt.datetime,
        ends: dt.datetime,
        *,
        ignoring: uuid.UUID | None = None,
    ) -> Listed | None:
        """Another booking holding this patient over the same stretch."""
        statement = (
            self._joined()
            .where(Appointment.patient_id == patient_id)
            .where(Appointment.status.not_in(RELEASED))
            .where(Appointment.scheduled_start < ends)
            .where(Appointment.scheduled_end > starts)
        )
        if ignoring is not None:
            statement = statement.where(Appointment.id != ignoring)
        found = await self._rows(statement.limit(1))
        return found[0] if found else None


class EventRepository(TenantScopedRepository[AppointmentEvent]):
    model = AppointmentEvent

    async def for_appointment(self, appointment_id: uuid.UUID) -> list[AppointmentEvent]:
        result = await self.session.execute(
            self.query()
            .where(AppointmentEvent.appointment_id == appointment_id)
            # The key is a UUIDv7, so two lines written in the same instant
            # still read back in the order they happened.
            .order_by(AppointmentEvent.created_at, AppointmentEvent.id)
        )
        return list(result.scalars().all())
