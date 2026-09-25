"""Queries for the platform's own screens.

The one place that reads across every clinic. Everything here comes back as
a count, a clinic's own details or the names of whoever runs it; no query in
this module selects a patient, a note, a bill or a file.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, case, func, or_, select

from app.core.permissions import OWNER
from app.models import (
    Appointment,
    AuditEntry,
    Doctor,
    Organization,
    OrganizationSubscription,
    Patient,
    Role,
    SubscriptionPlan,
    User,
    UserRole,
)
from app.models.doctor import ACTIVE as DOCTOR_ACTIVE
from app.models.patient import ARCHIVED
from app.repositories.base import UnscopedRepository
from app.repositories.prescriptions import _as_typed

# What a clinic's history on the platform screens is made of. Everything
# else in its audit log is the clinic's own business.
PLATFORM_ACTIONS = ("platform.suspended", "platform.reactivated", "platform.plan_changed")

SORTS: dict[str, Any] = {
    "-created_at": (Organization.created_at.desc(), Organization.id.desc()),
    "created_at": (Organization.created_at, Organization.id),
    "name": (func.lower(Organization.name), Organization.id),
}


@dataclass(frozen=True)
class ClinicRow:
    clinic: Organization
    plan: SubscriptionPlan | None
    trial_ends_at: dt.datetime | None
    doctors: int
    staff: int
    patients: int
    appointments_this_month: int
    last_active_at: dt.datetime | None


@dataclass(frozen=True)
class Owner:
    name: str
    email: str


def _counted(model: Any, *conditions: ColumnElement[bool]) -> ColumnElement[int]:
    statement = (
        select(func.count())
        .select_from(model)
        .where(model.organization_id == Organization.id)
        .correlate(Organization)
    )
    for condition in conditions:
        statement = statement.where(condition)
    return statement.scalar_subquery()


_ON_PLAN = SubscriptionPlan.id == OrganizationSubscription.plan_id


def month_start(now: dt.datetime | None = None) -> dt.datetime:
    """The platform counts in UTC months; each clinic's own screens count in
    its own time zone. The difference is a few hours at a month's edge."""
    moment = now or dt.datetime.now(dt.UTC)
    return dt.datetime(moment.year, moment.month, 1, tzinfo=dt.UTC)


def held_plan(fallback_id: uuid.UUID) -> ColumnElement[uuid.UUID]:
    """The plan a clinic is held to: the one chosen for it, or the fallback
    once a trial has run out or when nothing was ever chosen."""
    return case(
        (OrganizationSubscription.trial_ends_at <= func.now(), fallback_id),
        else_=func.coalesce(OrganizationSubscription.plan_id, fallback_id),
    )


class PlatformRepository(UnscopedRepository[Organization]):
    model = Organization

    def _rows(self) -> Select[Any]:
        last_active = (
            select(func.max(User.last_login_at))
            .where(User.organization_id == Organization.id)
            .correlate(Organization)
            .scalar_subquery()
        )
        return (
            select(
                Organization,
                SubscriptionPlan,
                OrganizationSubscription.trial_ends_at,
                _counted(Doctor, Doctor.status == DOCTOR_ACTIVE),
                _counted(User, User.status == "active"),
                _counted(Patient, Patient.status != ARCHIVED),
                _counted(Appointment, Appointment.created_at >= month_start()),
                last_active,
            )
            .outerjoin(
                OrganizationSubscription,
                OrganizationSubscription.organization_id == Organization.id,
            )
            .outerjoin(SubscriptionPlan, _ON_PLAN)
        )

    @staticmethod
    def _row(row: Any) -> ClinicRow:
        return ClinicRow(
            clinic=row[0],
            plan=row[1],
            trial_ends_at=row[2],
            doctors=int(row[3]),
            staff=int(row[4]),
            patients=int(row[5]),
            appointments_this_month=int(row[6]),
            last_active_at=row[7],
        )

    @staticmethod
    def _matching(typed: str) -> ColumnElement[bool]:
        like = f"%{_as_typed(typed.strip().lower())}%"
        owners = (
            select(User.organization_id)
            .where(User.organization_id.is_not(None))
            .where(func.lower(User.email).like(like, escape="\\"))
        )
        return or_(
            func.lower(Organization.name).like(like, escape="\\"),
            Organization.slug.like(like, escape="\\"),
            Organization.id.in_(owners),
        )

    async def listed(
        self,
        *,
        typed: str | None,
        status: str | None,
        plan_id: uuid.UUID | None,
        fallback_id: uuid.UUID,
        sort: str,
        limit: int,
        offset: int,
    ) -> tuple[list[ClinicRow], int]:
        conditions: list[ColumnElement[bool]] = []
        if typed:
            conditions.append(self._matching(typed))
        if status:
            conditions.append(Organization.status == status)
        if plan_id:
            conditions.append(held_plan(fallback_id) == plan_id)

        statement = self._rows()
        counting = (
            select(func.count())
            .select_from(Organization)
            .outerjoin(
                OrganizationSubscription,
                OrganizationSubscription.organization_id == Organization.id,
            )
            .outerjoin(SubscriptionPlan, _ON_PLAN)
        )
        for condition in conditions:
            statement = statement.where(condition)
            counting = counting.where(condition)

        result = await self.session.execute(
            statement.order_by(*SORTS[sort]).limit(limit).offset(offset)
        )
        total = await self.session.execute(counting)
        return [self._row(row) for row in result.all()], int(total.scalar_one())

    async def one(self, organization_id: uuid.UUID) -> ClinicRow | None:
        result = await self.session.execute(
            self._rows().where(Organization.id == organization_id)
        )
        row = result.first()
        return self._row(row) if row else None

    async def by_status(self) -> dict[str, int]:
        result = await self.session.execute(
            select(Organization.status, func.count()).group_by(Organization.status)
        )
        return {status: int(count) for status, count in result.all()}

    async def owners(self, organization_ids: list[uuid.UUID]) -> dict[uuid.UUID, Owner]:
        """Whoever has run each clinic longest, which is usually whoever made
        it. That is who the platform would get in touch with."""
        if not organization_ids:
            return {}
        result = await self.session.execute(
            select(User.organization_id, User.first_name, User.last_name, User.email)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.organization_id.in_(organization_ids))
            .where(Role.slug == OWNER)
            .order_by(User.organization_id, User.status, User.created_at)
            .distinct(User.organization_id)
        )
        return {
            row[0]: Owner(name=f"{row[1]} {row[2]}".strip(), email=row[3])
            for row in result.all()
        }

    async def members(self, organization_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(User.id).where(User.organization_id == organization_id)
        )
        return list(result.scalars().all())

    async def history(self, organization_id: uuid.UUID, *, limit: int = 20) -> list[AuditEntry]:
        result = await self.session.execute(
            select(AuditEntry)
            .where(AuditEntry.organization_id == organization_id)
            .where(AuditEntry.action.in_(PLATFORM_ACTIONS))
            .order_by(AuditEntry.created_at.desc(), AuditEntry.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def totals(self) -> dict[str, int]:
        since = month_start()
        statements = {
            "accounts": select(func.count())
            .select_from(User)
            .where(User.organization_id.is_not(None))
            .where(User.status == "active"),
            "doctors": select(func.count())
            .select_from(Doctor)
            .where(Doctor.status == DOCTOR_ACTIVE),
            "patients": select(func.count())
            .select_from(Patient)
            .where(Patient.status != ARCHIVED),
            "appointments_this_month": select(func.count())
            .select_from(Appointment)
            .where(Appointment.created_at >= since),
            "new_clinics_this_month": select(func.count())
            .select_from(Organization)
            .where(Organization.created_at >= since),
        }
        totals: dict[str, int] = {}
        for name, statement in statements.items():
            totals[name] = int((await self.session.execute(statement)).scalar_one())
        return totals

    async def signups_by_week(self, weeks: int) -> list[tuple[dt.date, int]]:
        """New clinics in each of the last few weeks, Monday to Sunday, UTC,
        with the quiet weeks filled in as zero."""
        today = dt.datetime.now(dt.UTC).date()
        first = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=weeks - 1)
        start = dt.datetime.combine(first, dt.time(), tzinfo=dt.UTC)
        week = func.date_trunc("week", func.timezone("UTC", Organization.created_at))
        result = await self.session.execute(
            select(week, func.count()).where(Organization.created_at >= start).group_by(week)
        )
        counted = {moment.date(): int(count) for moment, count in result.all()}
        return [
            (first + dt.timedelta(weeks=n), counted.get(first + dt.timedelta(weeks=n), 0))
            for n in range(weeks)
        ]

    async def clinics_on_plans(self, fallback_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """How many clinics each plan holds right now. A lapsed trial counts
        against the fallback, not the plan that was being tried."""
        lapsed = func.coalesce(OrganizationSubscription.trial_ends_at <= func.now(), False)
        result = await self.session.execute(
            select(OrganizationSubscription.plan_id, lapsed, func.count())
            .select_from(Organization)
            .outerjoin(
                OrganizationSubscription,
                OrganizationSubscription.organization_id == Organization.id,
            )
            .group_by(OrganizationSubscription.plan_id, lapsed)
        )
        held: dict[uuid.UUID, int] = {}
        for plan_id, over, count in result.all():
            key = fallback_id if plan_id is None or over else plan_id
            held[key] = held.get(key, 0) + int(count)
        return held

    async def plans(self) -> list[SubscriptionPlan]:
        result = await self.session.execute(
            select(SubscriptionPlan).order_by(SubscriptionPlan.position, SubscriptionPlan.name)
        )
        return list(result.scalars().all())
