"""Queries for the day's queue.

Everything goes through the scoped repository, so another clinic's queue
reads as absent rather than forbidden.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, func, select

from app.models import (
    Appointment,
    Consultation,
    Doctor,
    Patient,
    Prescription,
    QueueEntry,
    Vitals,
)
from app.models.queue import LIVE
from app.repositories.appointments import allergy_count
from app.repositories.base import TenantScopedRepository


@dataclass(frozen=True)
class Placed:
    entry: QueueEntry
    patient: Patient
    doctor: Doctor
    appointment: Appointment | None
    allergy_count: int
    consultation_id: uuid.UUID | None = None
    prescription_id: uuid.UUID | None = None
    vitals: Vitals | None = None


class QueueRepository(TenantScopedRepository[QueueEntry]):
    model = QueueEntry

    def _joined(self) -> Select[Any]:
        return (
            select(
                QueueEntry,
                Patient,
                Doctor,
                Appointment,
                allergy_count(),
                Consultation.id,
                Prescription.id,
                Vitals,
            )
            .join(Patient, Patient.id == QueueEntry.patient_id)
            .join(Doctor, Doctor.id == QueueEntry.doctor_id)
            .outerjoin(Appointment, Appointment.id == QueueEntry.appointment_id)
            .outerjoin(Consultation, Consultation.queue_entry_id == QueueEntry.id)
            # The prescription standing for the visit, which the desk prints.
            .outerjoin(
                Prescription,
                and_(
                    Prescription.consultation_id == Consultation.id,
                    Prescription.status == "issued",
                ),
            )
            .outerjoin(Vitals, Vitals.queue_entry_id == QueueEntry.id)
            .where(QueueEntry.organization_id == self.organization_id)
        )

    async def _rows(self, statement: Select[Any]) -> list[Placed]:
        result = await self.session.execute(statement)
        return [
            Placed(
                entry=row[0],
                patient=row[1],
                doctor=row[2],
                appointment=row[3],
                allergy_count=row[4],
                consultation_id=row[5],
                prescription_id=row[6],
                vitals=row[7],
            )
            for row in result.all()
        ]

    async def one(self, entry_id: uuid.UUID, *, lock: bool = False) -> Placed | None:
        """One place, locked when it is about to change.

        Only the place itself: the appointment sits on the nullable side of
        an outer join, which Postgres will not lock, so it is locked on its
        own with lock_appointment.
        """
        statement = self._joined().where(QueueEntry.id == entry_id)
        if lock:
            statement = statement.with_for_update(of=QueueEntry).execution_options(
                populate_existing=True
            )
        found = await self._rows(statement)
        return found[0] if found else None

    async def first_with(
        self, doctor_id: uuid.UUID, day: dt.date, status: str
    ) -> QueueEntry | None:
        result = await self.session.execute(
            self.query()
            .where(QueueEntry.doctor_id == doctor_id)
            .where(QueueEntry.token_date == day)
            .where(QueueEntry.status == status)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def on_day(self, day: dt.date, *, doctor_id: uuid.UUID | None = None) -> list[Placed]:
        statement = self._joined().where(QueueEntry.token_date == day)
        if doctor_id is not None:
            statement = statement.where(QueueEntry.doctor_id == doctor_id)
        return await self._rows(
            statement.order_by(QueueEntry.doctor_id, QueueEntry.token_number)
        )

    async def for_appointments(self, appointment_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
        """The token each of these appointments was given, where it has one."""
        if not appointment_ids:
            return {}
        result = await self.session.execute(
            select(QueueEntry.appointment_id, QueueEntry.token_number)
            .where(QueueEntry.organization_id == self.organization_id)
            .where(QueueEntry.appointment_id.in_(appointment_ids))
        )
        return {row[0]: row[1] for row in result.all() if row[0] is not None}

    async def live_place(self, patient_id: uuid.UUID, day: dt.date) -> Placed | None:
        found = await self._rows(
            self._joined()
            .where(QueueEntry.patient_id == patient_id)
            .where(QueueEntry.token_date == day)
            .where(QueueEntry.status.in_(LIVE))
            .limit(1)
        )
        return found[0] if found else None

    async def next_token(self, doctor_id: uuid.UUID, day: dt.date) -> int:
        """The number after the last one this doctor handed out today.

        The caller holds a lock on the doctor's row first, so two desks
        checking patients in for the same doctor take turns rather than both
        reading the same highest number.
        """
        result = await self.session.execute(
            select(func.coalesce(func.max(QueueEntry.token_number), 0))
            .where(QueueEntry.organization_id == self.organization_id)
            .where(QueueEntry.doctor_id == doctor_id)
            .where(QueueEntry.token_date == day)
        )
        return int(result.scalar_one()) + 1

    async def lock_appointment(self, appointment_id: uuid.UUID) -> None:
        await self.session.execute(
            select(Appointment)
            .where(Appointment.organization_id == self.organization_id)
            .where(Appointment.id == appointment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def lock_doctor(self, doctor_id: uuid.UUID) -> None:
        await self.session.execute(
            select(Doctor.id)
            .where(Doctor.organization_id == self.organization_id)
            .where(Doctor.id == doctor_id)
            .with_for_update()
        )
