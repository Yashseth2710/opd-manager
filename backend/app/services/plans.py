"""What each clinic's plan allows, and the one place that says no.

Every limit is checked here and nowhere else, and feature code names a
measure, never a plan. A new clinic tries the largest plan for a month and
then falls back to the free one, unless the platform has chosen a plan for
it in the meantime.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.core.exceptions import PlanLimitReached
from app.models import (
    Appointment,
    Doctor,
    Invitation,
    Organization,
    OrganizationSubscription,
    Patient,
    PatientDocument,
    SubscriptionPlan,
    User,
)
from app.models.doctor import ACTIVE as DOCTOR_ACTIVE
from app.models.invitation import PENDING
from app.models.patient import ARCHIVED

TRIAL_DAYS = 30
TRIAL_PLAN = "group"
FALLBACK_PLAN = "starter"

# Written into an empty database, and never over a plan somebody has edited.
DEFAULT_PLANS: tuple[dict[str, Any], ...] = (
    {
        "slug": "starter",
        "name": "Starter",
        "description": "One or two doctors getting going.",
        "price_monthly": Decimal("0.00"),
        "limits": {
            "max_doctors": 2,
            "max_staff": 5,
            "max_patients": 1000,
            "max_appointments_per_month": 600,
            "max_storage_mb": 500,
        },
        "position": 1,
    },
    {
        "slug": "clinic",
        "name": "Clinic",
        "description": "A busy practice with a front desk.",
        "price_monthly": Decimal("1499.00"),
        "limits": {
            "max_doctors": 8,
            "max_staff": 25,
            "max_patients": 20000,
            "max_appointments_per_month": 5000,
            "max_storage_mb": 5120,
        },
        "position": 2,
    },
    {
        "slug": "group",
        "name": "Group",
        "description": "Several consultants under one roof, with nothing capped.",
        "price_monthly": Decimal("4999.00"),
        "limits": {
            "max_doctors": None,
            "max_staff": None,
            "max_patients": None,
            "max_appointments_per_month": None,
            "max_storage_mb": None,
        },
        "position": 3,
    },
)

MEASURES = {
    "max_doctors": "doctors",
    "max_staff": "staff",
    "max_patients": "patients",
    "max_appointments_per_month": "appointments_this_month",
    "max_storage_mb": "storage_mb",
}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def ensure_plans(session: AsyncSession) -> dict[str, SubscriptionPlan]:
    """The plans, written first if the database has none. Offered whole and
    left to the unique slug to drop, for the same reason as the permission
    catalogue: two clinics signing up at once on a fresh database."""
    await session.execute(
        insert(SubscriptionPlan)
        .values([{"id": uuid7(), **plan} for plan in DEFAULT_PLANS])
        .on_conflict_do_nothing(index_elements=[SubscriptionPlan.slug])
    )
    await session.flush()
    result = await session.execute(select(SubscriptionPlan))
    return {plan.slug: plan for plan in result.scalars().all()}


async def start_trial(session: AsyncSession, organization_id: uuid.UUID) -> None:
    trial = await plan_named(session, TRIAL_PLAN)
    session.add(
        OrganizationSubscription(
            organization_id=organization_id,
            plan_id=trial.id,
            trial_ends_at=_now() + dt.timedelta(days=TRIAL_DAYS),
        )
    )
    await session.flush()


@dataclass(frozen=True)
class Standing:
    """The plan a clinic is held to right now, and how it got there."""

    plan: SubscriptionPlan
    chosen: SubscriptionPlan
    trial_ends_at: dt.datetime | None

    @property
    def on_trial(self) -> bool:
        return self.trial_ends_at is not None and self.trial_ends_at > _now()

    @property
    def trial_over(self) -> bool:
        return self.trial_ends_at is not None and self.trial_ends_at <= _now()


async def plan_named(session: AsyncSession, slug: str) -> SubscriptionPlan:
    result = await session.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.slug == slug)
    )
    found = result.scalar_one_or_none()
    return found if found is not None else (await ensure_plans(session))[slug]


async def standing(session: AsyncSession, organization_id: uuid.UUID) -> Standing:
    """One query in the usual case. The fallback plan is looked up only for a
    clinic that needs it."""
    result = await session.execute(
        select(OrganizationSubscription, SubscriptionPlan)
        .join(SubscriptionPlan, SubscriptionPlan.id == OrganizationSubscription.plan_id)
        .where(OrganizationSubscription.organization_id == organization_id)
    )
    row = result.first()
    if row is None:
        fallback = await plan_named(session, FALLBACK_PLAN)
        return Standing(plan=fallback, chosen=fallback, trial_ends_at=None)
    subscription, chosen = row
    ends = subscription.trial_ends_at
    if ends is not None and ends <= _now():
        fallback = await plan_named(session, FALLBACK_PLAN)
        return Standing(plan=fallback, chosen=chosen, trial_ends_at=ends)
    return Standing(plan=chosen, chosen=chosen, trial_ends_at=ends)


async def choose(
    session: AsyncSession, organization_id: uuid.UUID, plan: SubscriptionPlan
) -> None:
    """Puts a clinic on a plan for good, ending any trial."""
    result = await session.execute(
        select(OrganizationSubscription).where(
            OrganizationSubscription.organization_id == organization_id
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        session.add(OrganizationSubscription(organization_id=organization_id, plan_id=plan.id))
    else:
        subscription.plan_id = plan.id
        subscription.trial_ends_at = None
    await session.flush()


def _month_start(clinic: Organization) -> dt.datetime:
    try:
        zone: dt.tzinfo = ZoneInfo(clinic.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = dt.UTC
    today = _now().astimezone(zone).date()
    return dt.datetime.combine(today.replace(day=1), dt.time(), tzinfo=zone)


async def _count(session: AsyncSession, clinic: Organization, measure: str) -> int:
    organization_id = clinic.id
    if measure == "max_doctors":
        statement = (
            select(func.count())
            .select_from(Doctor)
            .where(Doctor.organization_id == organization_id)
            .where(Doctor.status == DOCTOR_ACTIVE)
        )
    elif measure == "max_staff":
        people = await session.execute(
            select(func.count())
            .select_from(User)
            .where(User.organization_id == organization_id)
            .where(User.status == "active")
        )
        waiting = await session.execute(
            select(func.count())
            .select_from(Invitation)
            .where(Invitation.organization_id == organization_id)
            .where(Invitation.status == PENDING)
            .where(Invitation.expires_at > _now())
        )
        return int(people.scalar_one()) + int(waiting.scalar_one())
    elif measure == "max_patients":
        statement = (
            select(func.count())
            .select_from(Patient)
            .where(Patient.organization_id == organization_id)
            .where(Patient.status != ARCHIVED)
        )
    elif measure == "max_appointments_per_month":
        statement = (
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.organization_id == organization_id)
            .where(Appointment.created_at >= _month_start(clinic))
        )
    elif measure == "max_storage_mb":
        statement = select(func.coalesce(func.sum(PatientDocument.size_bytes), 0)).where(
            PatientDocument.organization_id == organization_id
        )
    else:
        raise ValueError(measure)
    result = await session.execute(statement)
    return int(result.scalar_one())


async def usage(session: AsyncSession, clinic: Organization) -> dict[str, int]:
    """Where the clinic stands on every measure. Storage is in bytes here and
    left to whoever shows it to round."""
    return {MEASURES[measure]: await _count(session, clinic, measure) for measure in MEASURES}


def _refusal(plan: SubscriptionPlan, measure: str, cap: int) -> str:
    name = plan.name
    return {
        "max_doctors": (
            f"The {name} plan allows {cap} active doctors. Stand one down, or move the "
            "clinic to a bigger plan."
        ),
        "max_staff": (
            f"The {name} plan allows {cap} people on staff, counting invitations still "
            "waiting. Suspend someone or withdraw an invitation, or move to a bigger plan."
        ),
        "max_patients": (
            f"The {name} plan allows {cap:,} patients on the books. Archive records the "
            "clinic no longer needs, or move to a bigger plan."
        ),
        "max_appointments_per_month": (
            f"The {name} plan allows {cap:,} bookings a month, and this month's are used "
            "up. Move to a bigger plan to keep booking."
        ),
        "max_storage_mb": (
            f"The {name} plan allows {cap:,} MB of files, and this one would go over. "
            "Remove files nobody needs, or move to a bigger plan."
        ),
    }[measure]


async def check(
    session: AsyncSession,
    organization_id: uuid.UUID,
    measure: str,
    *,
    adding_bytes: int = 0,
) -> None:
    """Refuses one more of something when the clinic's plan is already full.

    The clinic's row is locked first when there is a cap to respect, so two
    desks adding the last allowed patient at the same moment take turns and
    the second one is refused, rather than both slipping in.
    """
    held = (await standing(session, organization_id)).plan
    cap = held.limit(measure)
    if cap is None:
        return
    clinic = (
        await session.execute(
            select(Organization).where(Organization.id == organization_id).with_for_update()
        )
    ).scalar_one()
    used = await _count(session, clinic, measure)
    if measure == "max_storage_mb":
        over = used + adding_bytes > cap * 1024 * 1024
    else:
        over = used + 1 > cap
    if over:
        raise PlanLimitReached(_refusal(held, measure, cap))
