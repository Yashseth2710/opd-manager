"""Queries for doctors, the week they sit, and the days they are away.

Everything goes through the scoped repository, so another clinic's doctor
reads as absent rather than forbidden.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Doctor, DoctorLeave, DoctorSchedule, User
from app.models.doctor import ACTIVE
from app.repositories.base import TenantScopedRepository

FULL_NAME = func.lower(Doctor.first_name + " " + Doctor.last_name)

# A clinic has tens of doctors, not thousands, so search is generous: a
# misheard speciality should still land on the right person.
SIMILARITY = 0.5

LIKE_ESCAPE = "\\"
_LIKE_WILDCARDS = (LIKE_ESCAPE, "%", "_")


def _literal(term: str) -> str:
    """Escapes what LIKE would otherwise read as a pattern.

    Without this a search for "%" matches every doctor at the clinic, which
    looks like a broken filter rather than a search.
    """
    escaped = term
    for character in _LIKE_WILDCARDS:
        escaped = escaped.replace(character, LIKE_ESCAPE + character)
    return escaped


@dataclass
class OnDuty:
    doctor: Doctor
    sits: bool
    leave: DoctorLeave | None


@dataclass
class Listed:
    doctor: Doctor
    working_days: int


class DoctorRepository(TenantScopedRepository[Doctor]):
    model = Doctor

    def _with_working_days(self) -> Select[tuple[Doctor, int]]:
        blocks = (
            select(
                DoctorSchedule.doctor_id.label("doctor_id"),
                func.count(func.distinct(DoctorSchedule.day_of_week)).label("days"),
            )
            .where(DoctorSchedule.organization_id == self.organization_id)
            .group_by(DoctorSchedule.doctor_id)
            .subquery()
        )
        return (
            self.query()
            .outerjoin(blocks, blocks.c.doctor_id == Doctor.id)
            .add_columns(func.coalesce(blocks.c.days, 0))
        )

    async def search(
        self,
        *,
        query: str = "",
        speciality: str = "",
        status: str | None = ACTIVE,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[Listed], int]:
        statement = self._with_working_days()
        counting = (
            select(func.count())
            .select_from(Doctor)
            .where(Doctor.organization_id == self.organization_id)
        )

        if status:
            statement = statement.where(Doctor.status == status)
            counting = counting.where(Doctor.status == status)

        if speciality:
            matches = func.lower(Doctor.speciality) == speciality.strip().lower()
            statement = statement.where(matches)
            counting = counting.where(matches)

        term = query.strip()
        if term:
            lowered = term.lower()
            like = f"%{_literal(lowered)}%"
            alternatives = [
                FULL_NAME.like(like, escape=LIKE_ESCAPE),
                func.lower(Doctor.speciality).like(like, escape=LIKE_ESCAPE),
                func.lower(Doctor.qualifications).like(like, escape=LIKE_ESCAPE),
                func.lower(Doctor.room).like(like, escape=LIKE_ESCAPE),
                # Tolerates the spelling a name was heard rather than read in.
                # word_similarity scores the term against the closest run of
                # words, so a surname alone still matches a full name.
                func.word_similarity(lowered, FULL_NAME) > SIMILARITY,
            ]
            statement = statement.where(or_(*alternatives))
            counting = counting.where(or_(*alternatives))

        statement = statement.order_by(
            Doctor.status,
            Doctor.last_name,
            Doctor.first_name,
            # Two doctors sharing a name would otherwise swap places between
            # pages and one of them would never be reachable.
            Doctor.id.desc(),
        )

        found = await self.session.execute(statement.limit(limit).offset(offset))
        total = await self.session.execute(counting)
        return (
            [Listed(doctor=row[0], working_days=int(row[1])) for row in found.all()],
            int(total.scalar_one()),
        )

    async def with_working_days(self, doctor_id: uuid.UUID) -> Listed | None:
        result = await self.session.execute(
            self._with_working_days().where(Doctor.id == doctor_id)
        )
        row = result.first()
        return None if row is None else Listed(doctor=row[0], working_days=int(row[1]))

    async def specialities(self, status: str | None = ACTIVE) -> list[str]:
        """What this clinic offers, among the doctors being looked at.

        Narrowed by the same status as the list, so a chip never offers a
        filter that comes back empty — a clinic whose only orthopaedist has
        been stood down is not offering orthopaedics this week.
        """
        statement = (
            select(Doctor.speciality)
            .where(Doctor.organization_id == self.organization_id)
            .where(Doctor.speciality.isnot(None))
            .where(Doctor.speciality != "")
        )
        if status:
            statement = statement.where(Doctor.status == status)
        result = await self.session.execute(statement.distinct().order_by(Doctor.speciality))
        return [row[0] for row in result.all()]

    async def linked_to(self, user_id: uuid.UUID, exclude_id: uuid.UUID | None = None) -> bool:
        statement = self.query().where(Doctor.user_id == user_id)
        if exclude_id:
            statement = statement.where(Doctor.id != exclude_id)
        result = await self.session.execute(statement.limit(1))
        return result.scalar_one_or_none() is not None

    async def for_account(self, user_id: uuid.UUID) -> Doctor | None:
        result = await self.session.execute(self.query().where(Doctor.user_id == user_id))
        return result.scalar_one_or_none()

    async def on_duty(self, day: dt.date) -> list[OnDuty]:
        """Every active doctor, whether they sit on this day, and the leave
        that takes the whole of it, in a single query.

        Read by the queue, which every screen showing it asks for every few
        seconds, so one round trip rather than one per question.
        """
        sits = (
            select(DoctorSchedule.id)
            .where(DoctorSchedule.organization_id == self.organization_id)
            .where(DoctorSchedule.doctor_id == Doctor.id)
            .where(DoctorSchedule.day_of_week == day.weekday())
            .correlate(Doctor)
            .exists()
        )
        away = (
            select(DoctorLeave.id)
            .where(DoctorLeave.organization_id == self.organization_id)
            .where(DoctorLeave.doctor_id == Doctor.id)
            .where(DoctorLeave.starts_on <= day)
            .where(DoctorLeave.ends_on >= day)
            .where(DoctorLeave.start_time.is_(None))
            .correlate(Doctor)
            .order_by(DoctorLeave.starts_on)
            .limit(1)
            .scalar_subquery()
        )
        result = await self.session.execute(
            self.query()
            .where(Doctor.status == ACTIVE)
            .add_columns(sits, away)
            .order_by(Doctor.last_name, Doctor.first_name)
        )
        rows = result.all()
        leave_ids = {row[2] for row in rows if row[2] is not None}
        leaves: dict[uuid.UUID, DoctorLeave] = {}
        if leave_ids:
            found = await self.session.execute(
                select(DoctorLeave).where(DoctorLeave.id.in_(leave_ids))
            )
            leaves = {leave.id: leave for leave in found.scalars().all()}
        return [
            OnDuty(
                doctor=row[0], sits=bool(row[1]), leave=leaves.get(row[2]) if row[2] else None
            )
            for row in rows
        ]

    async def registered_as(
        self, number: str, exclude_id: uuid.UUID | None = None
    ) -> Doctor | None:
        statement = self.query().where(
            func.lower(Doctor.registration_number) == number.strip().lower()
        )
        if exclude_id:
            statement = statement.where(Doctor.id != exclude_id)
        result = await self.session.execute(statement.limit(1))
        return result.scalar_one_or_none()


class ScheduleRepository(TenantScopedRepository[DoctorSchedule]):
    model = DoctorSchedule

    async def for_doctor(self, doctor_id: uuid.UUID) -> list[DoctorSchedule]:
        result = await self.session.execute(
            self.query()
            .where(DoctorSchedule.doctor_id == doctor_id)
            .order_by(DoctorSchedule.day_of_week, DoctorSchedule.start_time)
        )
        return list(result.scalars().all())

    async def on_day(self, doctor_id: uuid.UUID, day_of_week: int) -> list[DoctorSchedule]:
        result = await self.session.execute(
            self.query()
            .where(DoctorSchedule.doctor_id == doctor_id)
            .where(DoctorSchedule.day_of_week == day_of_week)
            .order_by(DoctorSchedule.start_time)
        )
        return list(result.scalars().all())

    async def clear(self, doctor_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(DoctorSchedule)
            .where(DoctorSchedule.organization_id == self.organization_id)
            .where(DoctorSchedule.doctor_id == doctor_id)
        )
        await self.session.flush()


class LeaveRepository(TenantScopedRepository[DoctorLeave]):
    model = DoctorLeave

    async def for_doctor(
        self, doctor_id: uuid.UUID, *, ending_after: dt.date | None = None
    ) -> list[DoctorLeave]:
        statement = self.query().where(DoctorLeave.doctor_id == doctor_id)
        if ending_after is not None:
            # Leave that finished last year is history nobody is looking for
            # on the profile; it stays in the table and out of the way.
            statement = statement.where(DoctorLeave.ends_on >= ending_after)
        result = await self.session.execute(statement.order_by(DoctorLeave.starts_on))
        return list(result.scalars().all())

    async def covering(self, doctor_id: uuid.UUID, day: dt.date) -> list[DoctorLeave]:
        result = await self.session.execute(
            self.query()
            .where(DoctorLeave.doctor_id == doctor_id)
            .where(DoctorLeave.starts_on <= day)
            .where(DoctorLeave.ends_on >= day)
            .order_by(DoctorLeave.start_time.nulls_first())
        )
        return list(result.scalars().all())

    async def belonging_to(
        self, doctor_id: uuid.UUID, leave_id: uuid.UUID
    ) -> DoctorLeave | None:
        result = await self.session.execute(
            self.query()
            .where(DoctorLeave.doctor_id == doctor_id)
            .where(DoctorLeave.id == leave_id)
            .limit(1)
        )
        return result.scalar_one_or_none()


async def names_of(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    result = await session.execute(
        select(User.id, User.first_name, User.last_name).where(User.id.in_(user_ids))
    )
    return {row[0]: f"{row[1]} {row[2]}".strip() for row in result.all()}
