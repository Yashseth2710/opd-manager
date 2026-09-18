"""Queries for consultation notes.

Scoped like everything else, so another clinic's notes read as absent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, delete, func, select

from app.models import (
    Consultation,
    ConsultationAddendum,
    ConsultationDiagnosis,
    Doctor,
    Patient,
    QueueEntry,
    User,
)
from app.repositories.appointments import allergy_count
from app.repositories.base import TenantScopedRepository


@dataclass
class Written:
    consultation: Consultation
    patient: Patient
    doctor: Doctor
    allergy_count: int
    token: int | None
    diagnoses: list[ConsultationDiagnosis] = field(default_factory=list)
    addendum_count: int = 0


@dataclass(frozen=True)
class Added:
    addendum: ConsultationAddendum
    written_by: str | None


def _addendum_count() -> Any:
    return (
        select(func.count())
        .select_from(ConsultationAddendum)
        .where(ConsultationAddendum.consultation_id == Consultation.id)
        .correlate(Consultation)
        .scalar_subquery()
    )


class ConsultationRepository(TenantScopedRepository[Consultation]):
    model = Consultation

    def _joined(self) -> Select[Any]:
        return (
            select(
                Consultation,
                Patient,
                Doctor,
                allergy_count(),
                QueueEntry.token_number,
                _addendum_count(),
            )
            .join(Patient, Patient.id == Consultation.patient_id)
            .join(Doctor, Doctor.id == Consultation.doctor_id)
            .outerjoin(QueueEntry, QueueEntry.id == Consultation.queue_entry_id)
            .where(Consultation.organization_id == self.organization_id)
        )

    async def _rows(self, statement: Select[Any]) -> list[Written]:
        result = await self.session.execute(statement)
        found = [
            Written(
                consultation=row[0],
                patient=row[1],
                doctor=row[2],
                allergy_count=row[3],
                token=row[4],
                addendum_count=row[5],
            )
            for row in result.all()
        ]
        await self._attach_diagnoses(found)
        return found

    async def _attach_diagnoses(self, found: list[Written]) -> None:
        if not found:
            return
        by_id = {written.consultation.id: written for written in found}
        result = await self.session.execute(
            select(ConsultationDiagnosis)
            .where(ConsultationDiagnosis.organization_id == self.organization_id)
            .where(ConsultationDiagnosis.consultation_id.in_(by_id))
            .order_by(ConsultationDiagnosis.consultation_id, ConsultationDiagnosis.position)
        )
        for diagnosis in result.scalars().all():
            by_id[diagnosis.consultation_id].diagnoses.append(diagnosis)

    async def one(self, consultation_id: uuid.UUID, *, lock: bool = False) -> Written | None:
        # Always read fresh: a save moments ago in this request leaves the
        # row's server-set timestamp expired, and loading it lazily is not
        # something an async session will do.
        statement = (
            self._joined()
            .where(Consultation.id == consultation_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update(of=Consultation)
        found = await self._rows(statement)
        return found[0] if found else None

    async def for_queue_entry(self, entry_id: uuid.UUID) -> Consultation | None:
        result = await self.session.execute(
            self.query().where(Consultation.queue_entry_id == entry_id)
        )
        return result.scalar_one_or_none()

    async def for_queue_entries(self, entry_ids: set[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        """Which of these places already have notes, keyed by place."""
        if not entry_ids:
            return {}
        result = await self.session.execute(
            select(Consultation.queue_entry_id, Consultation.id)
            .where(Consultation.organization_id == self.organization_id)
            .where(Consultation.queue_entry_id.in_(entry_ids))
        )
        return {row[0]: row[1] for row in result.all() if row[0] is not None}

    async def for_appointment(self, appointment_id: uuid.UUID) -> Consultation | None:
        result = await self.session.execute(
            self.query().where(Consultation.appointment_id == appointment_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def listed(
        self,
        *,
        doctor_id: uuid.UUID | None,
        patient_id: uuid.UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Written], int]:
        conditions: list[Any] = []
        if doctor_id is not None:
            conditions.append(Consultation.doctor_id == doctor_id)
        if patient_id is not None:
            conditions.append(Consultation.patient_id == patient_id)
        if status is not None:
            conditions.append(Consultation.status == status)

        statement = self._joined()
        counted = (
            select(func.count())
            .select_from(Consultation)
            .where(Consultation.organization_id == self.organization_id)
        )
        for condition in conditions:
            statement = statement.where(condition)
            counted = counted.where(condition)

        total = int((await self.session.execute(counted)).scalar_one())
        found = await self._rows(
            statement.order_by(Consultation.started_at.desc(), Consultation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return found, total

    async def replace_diagnoses(
        self, consultation_id: uuid.UUID, entries: list[tuple[str, bool]]
    ) -> None:
        await self.session.execute(
            delete(ConsultationDiagnosis)
            .where(ConsultationDiagnosis.organization_id == self.organization_id)
            .where(ConsultationDiagnosis.consultation_id == consultation_id)
        )
        for position, (label, is_primary) in enumerate(entries):
            self.session.add(
                ConsultationDiagnosis(
                    organization_id=self.organization_id,
                    consultation_id=consultation_id,
                    label=label,
                    is_primary=is_primary,
                    position=position,
                )
            )
        await self.session.flush()

    async def addenda(self, consultation_id: uuid.UUID) -> list[Added]:
        result = await self.session.execute(
            select(ConsultationAddendum, User)
            .outerjoin(User, User.id == ConsultationAddendum.written_by_id)
            .where(ConsultationAddendum.organization_id == self.organization_id)
            .where(ConsultationAddendum.consultation_id == consultation_id)
            .order_by(ConsultationAddendum.created_at, ConsultationAddendum.id)
        )
        return [
            Added(addendum=row[0], written_by=row[1].full_name if row[1] else None)
            for row in result.all()
        ]

    async def add_addendum(
        self, consultation_id: uuid.UUID, body: str, written_by_id: uuid.UUID
    ) -> ConsultationAddendum:
        addendum = ConsultationAddendum(
            organization_id=self.organization_id,
            consultation_id=consultation_id,
            body=body,
            written_by_id=written_by_id,
        )
        self.session.add(addendum)
        await self.session.flush()
        return addendum
