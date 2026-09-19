"""Queries for vital signs, scoped to the clinic like everything else."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import aliased

from app.models import Patient, QueueEntry, User, Vitals
from app.repositories.base import TenantScopedRepository


@dataclass(frozen=True)
class Taken:
    vitals: Vitals
    patient: Patient
    entry: QueueEntry
    taken_by: str | None
    changed_by: str | None


class VitalsRepository(TenantScopedRepository[Vitals]):
    model = Vitals

    def _joined(self) -> Select[Any]:
        taker = aliased(User)
        changer = aliased(User)
        return (
            select(Vitals, Patient, QueueEntry, taker, changer)
            .join(Patient, Patient.id == Vitals.patient_id)
            .join(QueueEntry, QueueEntry.id == Vitals.queue_entry_id)
            .outerjoin(taker, taker.id == Vitals.taken_by_id)
            .outerjoin(changer, changer.id == Vitals.changed_by_id)
            .where(Vitals.organization_id == self.organization_id)
        )

    async def _rows(self, statement: Select[Any]) -> list[Taken]:
        result = await self.session.execute(statement)
        return [
            Taken(
                vitals=row[0],
                patient=row[1],
                entry=row[2],
                taken_by=row[3].full_name if row[3] else None,
                changed_by=row[4].full_name if row[4] else None,
            )
            for row in result.all()
        ]

    async def one(self, vitals_id: uuid.UUID, *, lock: bool = False) -> Taken | None:
        statement = self._joined().where(Vitals.id == vitals_id)
        if lock:
            statement = statement.with_for_update(of=Vitals).execution_options(
                populate_existing=True
            )
        found = await self._rows(statement)
        return found[0] if found else None

    async def for_entry(self, entry_id: uuid.UUID) -> Taken | None:
        found = await self._rows(
            self._joined()
            .where(Vitals.queue_entry_id == entry_id)
            .execution_options(populate_existing=True)
        )
        return found[0] if found else None

    async def for_entries(self, entry_ids: set[uuid.UUID]) -> dict[uuid.UUID, Taken]:
        if not entry_ids:
            return {}
        found = await self._rows(self._joined().where(Vitals.queue_entry_id.in_(entry_ids)))
        return {taken.vitals.queue_entry_id: taken for taken in found}

    async def for_patient(
        self, patient_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Taken], int]:
        counted = (
            select(func.count())
            .select_from(Vitals)
            .where(Vitals.organization_id == self.organization_id)
            .where(Vitals.patient_id == patient_id)
        )
        total = int((await self.session.execute(counted)).scalar_one())
        found = await self._rows(
            self._joined()
            .where(Vitals.patient_id == patient_id)
            .order_by(Vitals.taken_at.desc(), Vitals.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return found, total
