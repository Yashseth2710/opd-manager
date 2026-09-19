"""Queries for lab orders and the values reported back for them."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, delete, func, or_, select

from app.models import Consultation, Doctor, LabOrder, LabResultValue, Patient, User, lab
from app.repositories.appointments import allergy_count
from app.repositories.base import TenantScopedRepository
from app.repositories.prescriptions import _as_typed


@dataclass
class Ordered:
    order: LabOrder
    patient: Patient
    doctor: Doctor
    allergy_count: int
    visit: Consultation
    values: list[LabResultValue] = field(default_factory=list)
    # Who did what, by name, for the record page.
    people: dict[str, str | None] = field(default_factory=dict)


_PEOPLE = ("ordered_by", "cancelled_by", "resulted_by", "changed_by", "reviewed_by")


class LabRepository(TenantScopedRepository[LabOrder]):
    model = LabOrder

    def _joined(self) -> Select[Any]:
        return (
            select(LabOrder, Patient, Doctor, allergy_count(), Consultation)
            .join(Patient, Patient.id == LabOrder.patient_id)
            .join(Doctor, Doctor.id == LabOrder.doctor_id)
            .join(Consultation, Consultation.id == LabOrder.consultation_id)
            .where(LabOrder.organization_id == self.organization_id)
        )

    async def _rows(self, statement: Select[Any]) -> list[Ordered]:
        result = await self.session.execute(statement)
        found = [
            Ordered(
                order=row[0], patient=row[1], doctor=row[2], allergy_count=row[3], visit=row[4]
            )
            for row in result.all()
        ]
        await self._attach_values(found)
        return found

    async def _attach_values(self, found: list[Ordered]) -> None:
        if not found:
            return
        by_id = {each.order.id: each for each in found}
        result = await self.session.execute(
            select(LabResultValue)
            .where(LabResultValue.organization_id == self.organization_id)
            .where(LabResultValue.lab_order_id.in_(by_id))
            .order_by(LabResultValue.lab_order_id, LabResultValue.position)
        )
        for value in result.scalars().all():
            by_id[value.lab_order_id].values.append(value)

    async def _attach_people(self, ordered: Ordered) -> None:
        order = ordered.order
        ids = {getattr(order, f"{role}_id") for role in _PEOPLE} - {None}
        names: dict[uuid.UUID, str] = {}
        if ids:
            result = await self.session.execute(select(User).where(User.id.in_(ids)))
            names = {user.id: user.full_name for user in result.scalars().all()}
        ordered.people = {role: names.get(getattr(order, f"{role}_id")) for role in _PEOPLE}

    async def one(self, order_id: uuid.UUID, *, lock: bool = False) -> Ordered | None:
        statement = (
            self._joined()
            .where(LabOrder.id == order_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update(of=LabOrder)
        found = await self._rows(statement)
        if not found:
            return None
        await self._attach_people(found[0])
        return found[0]

    async def active_for_visit(self, consultation_id: uuid.UUID) -> list[LabOrder]:
        result = await self.session.execute(
            self.query()
            .where(LabOrder.consultation_id == consultation_id)
            .where(LabOrder.status != lab.CANCELLED)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def listed(
        self,
        *,
        patient_id: uuid.UUID | None = None,
        consultation_id: uuid.UUID | None = None,
        doctor_id: uuid.UUID | None = None,
        statuses: tuple[str, ...] | None = None,
        typed: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Ordered], int]:
        conditions: list[Any] = [LabOrder.organization_id == self.organization_id]
        if patient_id is not None:
            conditions.append(LabOrder.patient_id == patient_id)
        if consultation_id is not None:
            conditions.append(LabOrder.consultation_id == consultation_id)
        if doctor_id is not None:
            conditions.append(LabOrder.doctor_id == doctor_id)
        if statuses:
            conditions.append(LabOrder.status.in_(statuses))
        if typed:
            needle = f"%{_as_typed(typed.lower())}%"
            conditions.append(
                or_(
                    func.lower(Patient.first_name + " " + Patient.last_name).like(
                        needle, escape="\\"
                    ),
                    func.lower(Patient.patient_number).like(needle, escape="\\"),
                    Patient.phone.like(needle, escape="\\"),
                    func.lower(LabOrder.order_number).like(needle, escape="\\"),
                    func.lower(LabOrder.test_name).like(needle, escape="\\"),
                )
            )

        counted = (
            select(func.count())
            .select_from(LabOrder)
            .join(Patient, Patient.id == LabOrder.patient_id)
            .where(*conditions)
        )
        total = int((await self.session.execute(counted)).scalar_one())

        # One visit's tests in the order they were asked for. What is still
        # waiting is oldest first, since that is the one that is late, with
        # anything urgent ahead of it; everything else newest first.
        waiting = statuses is not None and set(statuses) <= set(lab.OPEN)
        order_by: list[Any]
        if consultation_id is not None:
            order_by = [LabOrder.ordered_at.asc(), LabOrder.id.asc()]
        elif waiting:
            order_by = [LabOrder.urgent.desc(), LabOrder.ordered_at.asc(), LabOrder.id.asc()]
        else:
            order_by = [LabOrder.ordered_at.desc(), LabOrder.id.desc()]
        found = await self._rows(
            self._joined().where(*conditions).order_by(*order_by).limit(limit).offset(offset)
        )
        return found, total

    async def counts(self, *, doctor_id: uuid.UUID | None = None) -> dict[str, int]:
        statement = (
            select(LabOrder.status, func.count())
            .where(LabOrder.organization_id == self.organization_id)
            .group_by(LabOrder.status)
        )
        if doctor_id is not None:
            statement = statement.where(LabOrder.doctor_id == doctor_id)
        result = await self.session.execute(statement)
        found = {status: 0 for status in lab.STATUSES}
        found.update({row[0]: int(row[1]) for row in result.all()})
        return found

    async def earlier_report(self, ordered: Ordered) -> Ordered | None:
        """This patient's last report of the same test before this one was
        asked for, to set each value beside."""
        order = ordered.order
        same = (
            LabOrder.test_code == order.test_code
            if order.test_code
            else func.lower(LabOrder.test_name) == order.test_name.lower()
        )
        found = await self._rows(
            self._joined()
            .where(LabOrder.patient_id == order.patient_id)
            .where(LabOrder.id != order.id)
            .where(LabOrder.status.in_((lab.RESULTED, lab.REVIEWED)))
            .where(same)
            .where(LabOrder.ordered_at < order.ordered_at)
            .order_by(LabOrder.reported_on.desc(), LabOrder.ordered_at.desc())
            .limit(1)
        )
        return found[0] if found else None

    async def replace_values(self, order_id: uuid.UUID, values: list[dict[str, Any]]) -> None:
        await self.session.execute(
            delete(LabResultValue)
            .where(LabResultValue.organization_id == self.organization_id)
            .where(LabResultValue.lab_order_id == order_id)
        )
        for position, value in enumerate(values):
            self.session.add(
                LabResultValue(
                    organization_id=self.organization_id,
                    lab_order_id=order_id,
                    position=position,
                    **value,
                )
            )
        await self.session.flush()

    async def times_ordered(self) -> tuple[dict[str, int], list[tuple[str, str | None, int]]]:
        """How often this clinic has asked for each listed test, and the
        tests it has typed in that the list does not carry."""
        listed = await self.session.execute(
            select(LabOrder.test_code, func.count())
            .where(LabOrder.organization_id == self.organization_id)
            .where(LabOrder.test_code.is_not(None))
            .group_by(LabOrder.test_code)
        )
        typed = await self.session.execute(
            select(func.min(LabOrder.test_name), func.min(LabOrder.category), func.count())
            .where(LabOrder.organization_id == self.organization_id)
            .where(LabOrder.test_code.is_(None))
            .group_by(func.lower(LabOrder.test_name))
            .order_by(func.count().desc())
            .limit(100)
        )
        return (
            {row[0]: int(row[1]) for row in listed.all()},
            [(row[0], row[1], int(row[2])) for row in typed.all()],
        )

    async def to_review(self, doctor_id: uuid.UUID, *, limit: int) -> tuple[list[Ordered], int]:
        return await self.listed(
            doctor_id=doctor_id, statuses=(lab.RESULTED,), limit=limit, offset=0
        )
