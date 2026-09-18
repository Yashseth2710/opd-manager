"""Queries for prescriptions and the medicine list.

Prescriptions are scoped to the clinic like everything else. The medicine
list is not: it is one published list shared by every clinic, and nothing a
clinic does writes to it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Numeric, Select, case, cast, delete, func, literal, or_, select

from app.models import Doctor, Medicine, Patient, Prescription, PrescriptionItem
from app.models import prescription as rx
from app.repositories.appointments import allergy_count
from app.repositories.base import TenantScopedRepository


@dataclass
class Written:
    prescription: Prescription
    patient: Patient
    doctor: Doctor
    allergy_count: int
    items: list[PrescriptionItem] = field(default_factory=list)


@dataclass(frozen=True)
class Suggestion:
    name: str
    presentation: str | None
    source: str
    times_prescribed: int


def _as_typed(text: str) -> str:
    """Escaped for LIKE, so a % or _ someone typed matches only itself."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class PrescriptionRepository(TenantScopedRepository[Prescription]):
    model = Prescription

    def _joined(self) -> Select[Any]:
        return (
            select(Prescription, Patient, Doctor, allergy_count())
            .join(Patient, Patient.id == Prescription.patient_id)
            .join(Doctor, Doctor.id == Prescription.doctor_id)
            .where(Prescription.organization_id == self.organization_id)
        )

    async def _rows(self, statement: Select[Any]) -> list[Written]:
        result = await self.session.execute(statement)
        found = [
            Written(prescription=row[0], patient=row[1], doctor=row[2], allergy_count=row[3])
            for row in result.all()
        ]
        await self._attach_items(found)
        return found

    async def _attach_items(self, found: list[Written]) -> None:
        if not found:
            return
        by_id = {written.prescription.id: written for written in found}
        result = await self.session.execute(
            select(PrescriptionItem)
            .where(PrescriptionItem.organization_id == self.organization_id)
            .where(PrescriptionItem.prescription_id.in_(by_id))
            .order_by(PrescriptionItem.prescription_id, PrescriptionItem.position)
        )
        for item in result.scalars().all():
            by_id[item.prescription_id].items.append(item)

    async def one(self, prescription_id: uuid.UUID, *, lock: bool = False) -> Written | None:
        statement = (
            self._joined()
            .where(Prescription.id == prescription_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update(of=Prescription)
        found = await self._rows(statement)
        return found[0] if found else None

    async def for_consultation(self, consultation_id: uuid.UUID) -> list[Written]:
        """Every prescription on one visit, the one being written or standing
        first and anything it replaced after."""
        return await self._rows(
            self._joined()
            .where(Prescription.consultation_id == consultation_id)
            .order_by(
                (Prescription.status == rx.REPLACED).asc(),
                Prescription.issued_at.desc().nulls_first(),
            )
            .execution_options(populate_existing=True)
        )

    async def draft_for(self, consultation_id: uuid.UUID) -> Prescription | None:
        result = await self.session.execute(
            self.query()
            .where(Prescription.consultation_id == consultation_id)
            .where(Prescription.status == rx.DRAFT)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def numbers(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(Prescription.id, Prescription.prescription_number)
            .where(Prescription.organization_id == self.organization_id)
            .where(Prescription.id.in_(ids))
        )
        return {row[0]: row[1] for row in result.all()}

    async def replacing(
        self, ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID, str | None]]:
        """For each of these, the prescription that replaced it, if one did."""
        if not ids:
            return {}
        result = await self.session.execute(
            select(Prescription.replaces_id, Prescription.id, Prescription.prescription_number)
            .where(Prescription.organization_id == self.organization_id)
            .where(Prescription.replaces_id.in_(ids))
        )
        return {row[0]: (row[1], row[2]) for row in result.all() if row[0] is not None}

    async def issued(
        self, *, patient_id: uuid.UUID | None, limit: int, offset: int
    ) -> tuple[list[Written], int]:
        """What has been handed to patients, newest first. Drafts are the
        doctor's until issued and are never listed."""
        conditions: list[Any] = [Prescription.status != rx.DRAFT]
        if patient_id is not None:
            conditions.append(Prescription.patient_id == patient_id)
        counted = (
            select(func.count())
            .select_from(Prescription)
            .where(Prescription.organization_id == self.organization_id, *conditions)
        )
        total = int((await self.session.execute(counted)).scalar_one())
        found = await self._rows(
            self._joined()
            .where(*conditions)
            .order_by(Prescription.issued_at.desc(), Prescription.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return found, total

    async def replace_items(
        self, prescription_id: uuid.UUID, lines: list[dict[str, Any]]
    ) -> None:
        await self.session.execute(
            delete(PrescriptionItem)
            .where(PrescriptionItem.organization_id == self.organization_id)
            .where(PrescriptionItem.prescription_id == prescription_id)
        )
        for position, line in enumerate(lines):
            self.session.add(
                PrescriptionItem(
                    organization_id=self.organization_id,
                    prescription_id=prescription_id,
                    position=position,
                    **line,
                )
            )
        await self.session.flush()

    async def items_of(self, prescription_id: uuid.UUID) -> list[PrescriptionItem]:
        result = await self.session.execute(
            select(PrescriptionItem)
            .where(PrescriptionItem.organization_id == self.organization_id)
            .where(PrescriptionItem.prescription_id == prescription_id)
            .order_by(PrescriptionItem.position)
        )
        return list(result.scalars().all())

    async def issued_for_consultations(
        self, consultation_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, uuid.UUID]:
        if not consultation_ids:
            return {}
        result = await self.session.execute(
            select(Prescription.consultation_id, Prescription.id)
            .where(Prescription.organization_id == self.organization_id)
            .where(Prescription.consultation_id.in_(consultation_ids))
            .where(Prescription.status == rx.ISSUED)
        )
        return {row[0]: row[1] for row in result.all()}

    async def suggestions(self, typed: str, *, limit: int) -> list[Suggestion]:
        """What this clinic has written before, most often first, then the
        published list. A name starting with what was typed beats one that
        merely contains it, and a near miss is offered only when nothing
        closer is."""
        needle = typed.lower()
        # Typed characters are matched as themselves: a % or _ in the box is
        # not a wildcard.
        literal_needle = _as_typed(needle)
        starts = f"{literal_needle}%"
        contains = f"%{literal_needle}%"

        name = func.lower(PrescriptionItem.medicine_name)
        own = await self.session.execute(
            select(
                PrescriptionItem.medicine_name,
                PrescriptionItem.presentation,
                func.count().label("times"),
            )
            .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
            .where(PrescriptionItem.organization_id == self.organization_id)
            .where(Prescription.status != rx.DRAFT)
            .where(name.like(contains, escape="\\"))
            .group_by(PrescriptionItem.medicine_name, PrescriptionItem.presentation)
            .order_by(name.like(starts, escape="\\").desc(), func.count().desc(), name)
            .limit(limit)
        )
        found = [
            Suggestion(
                name=row[0], presentation=row[1], source="clinic", times_prescribed=row[2]
            )
            for row in own.all()
        ]

        listed_name = func.lower(Medicine.name)
        closeness = func.similarity(listed_name, literal(needle))
        form = func.lower(func.coalesce(Medicine.presentation, ""))
        # What an outpatient doctor writes most: tablets and capsules, then
        # syrups and other oral forms, and injections last.
        usual = case(
            (or_(form.like("tablet%"), form.like("capsule%")), 0),
            (or_(form.like("oral%"), form.like("dry syrup%"), form.like("syrup%")), 1),
            (or_(form.like("injection%"), form.like("powder for injection%")), 3),
            else_=2,
        )
        # 500 mg before 1000 mg, which a plain sort of the text gets wrong.
        strength = cast(func.substring(Medicine.presentation, r"[0-9]+(?:\.[0-9]+)?"), Numeric)
        listed = await self.session.execute(
            select(Medicine.name, Medicine.presentation)
            .where(or_(listed_name.like(contains, escape="\\"), closeness > 0.3))
            .order_by(
                listed_name.like(starts, escape="\\").desc(),
                listed_name.like(contains, escape="\\").desc(),
                closeness.desc(),
                listed_name,
                usual,
                strength,
                Medicine.presentation,
            )
            .limit(limit * 2)
        )
        seen = {(s.name.lower(), (s.presentation or "").lower()) for s in found}
        for row in listed.all():
            key = (row[0].lower(), (row[1] or "").lower())
            if key in seen:
                continue
            seen.add(key)
            found.append(
                Suggestion(name=row[0], presentation=row[1], source="list", times_prescribed=0)
            )
        return found[:limit]
