"""Running the platform: which clinics exist, what they are on, and stopping
one when it has to be stopped.

What the platform does to a clinic is written into that clinic's own audit
log, under the name of whoever did it, so the clinic can always see it.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound, ValidationFailed
from app.models import Organization, OrganizationSubscription, SubscriptionPlan
from app.models.organization import ACTIVE, PENDING, SUSPENDED
from app.repositories.platform import ClinicRow, PlatformRepository
from app.schemas.platform import PlanUpdate
from app.services import events, plans, sessions

SIGNUP_WEEKS = 12


class ClinicNotFound(NotFound):
    code = "PLATFORM_CLINIC_NOT_FOUND"
    message = "That clinic could not be found."


class PlanNotFound(NotFound):
    code = "PLATFORM_PLAN_NOT_FOUND"
    message = "That plan could not be found."


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _standing(row: ClinicRow, fallback: SubscriptionPlan) -> dict[str, Any]:
    chosen = row.plan or fallback
    ends = row.trial_ends_at
    over = ends is not None and ends <= _now()
    held = fallback if over or row.plan is None else chosen
    return {
        "plan_id": held.id,
        "plan_name": held.name,
        "chosen_name": chosen.name,
        "trial_ends_at": ends,
        "on_trial": ends is not None and not over,
        "trial_over": over,
    }


def _row(row: ClinicRow, fallback: SubscriptionPlan, owner: Any) -> dict[str, Any]:
    clinic = row.clinic
    return {
        "id": clinic.id,
        "name": clinic.name,
        "slug": clinic.slug,
        "status": clinic.status,
        "created_at": clinic.created_at,
        "set_up": clinic.is_set_up,
        "standing": _standing(row, fallback),
        "owner": {"name": owner.name, "email": owner.email} if owner else None,
        "doctors": row.doctors,
        "staff": row.staff,
        "patients": row.patients,
        "appointments_this_month": row.appointments_this_month,
        "last_active_at": row.last_active_at,
    }


async def clinics(
    session: AsyncSession,
    *,
    typed: str | None,
    status: str | None,
    plan_id: uuid.UUID | None,
    sort: str,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    platform = PlatformRepository(session)
    fallback = await plans.plan_named(session, plans.FALLBACK_PLAN)
    rows, total = await platform.listed(
        typed=" ".join((typed or "").split()) or None,
        status=status,
        plan_id=plan_id,
        fallback_id=fallback.id,
        sort=sort,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    owners = await platform.owners([row.clinic.id for row in rows])
    statuses = await platform.by_status()
    return {
        "items": [_row(row, fallback, owners.get(row.clinic.id)) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(math.ceil(total / per_page), 1),
        "statuses": {
            "all": sum(statuses.values()),
            PENDING: statuses.get(PENDING, 0),
            ACTIVE: statuses.get(ACTIVE, 0),
            SUSPENDED: statuses.get(SUSPENDED, 0),
        },
    }


async def clinic(session: AsyncSession, organization_id: uuid.UUID) -> dict[str, Any]:
    platform = PlatformRepository(session)
    row = await platform.one(organization_id)
    if row is None:
        raise ClinicNotFound
    fallback = await plans.plan_named(session, plans.FALLBACK_PLAN)
    owners = await platform.owners([organization_id])
    held = (await plans.standing(session, organization_id)).plan
    used = await plans.usage(session, row.clinic)
    storage_mb = math.ceil(used["storage_mb"] / (1024 * 1024))
    usage = {
        "doctors": {"used": used["doctors"], "limit": held.limit("max_doctors")},
        "staff": {"used": used["staff"], "limit": held.limit("max_staff")},
        "patients": {"used": used["patients"], "limit": held.limit("max_patients")},
        "appointments_this_month": {
            "used": used["appointments_this_month"],
            "limit": held.limit("max_appointments_per_month"),
        },
        "storage_mb": {"used": storage_mb, "limit": held.limit("max_storage_mb")},
    }
    address = row.clinic.address or {}
    return {
        **_row(row, fallback, owners.get(organization_id)),
        "phone": row.clinic.phone,
        "email": row.clinic.email,
        "city": str(address.get("city") or "") or None,
        "timezone": row.clinic.timezone,
        "usage": usage,
        "history": [
            {
                "id": entry.id,
                "action": entry.action,
                "actor_name": entry.actor_name,
                "changes": entry.changes,
                "created_at": entry.created_at,
            }
            for entry in await platform.history(organization_id)
        ],
    }


async def _locked_clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    """Locked, so two administrators acting on one clinic at the same moment
    take turns and the second sees what the first did."""
    result = await session.execute(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    found = result.scalar_one_or_none()
    if found is None:
        raise ClinicNotFound
    return found


async def suspend(
    session: AsyncSession, *, organization_id: uuid.UUID, reason: str, actor: events.Actor
) -> Organization:
    """Stops a clinic. Its people are refused from the next request on, and
    every session they hold is ended so none of them can be renewed. Nothing
    the clinic has recorded is touched."""
    found = await _locked_clinic(session, organization_id)
    if found.status == SUSPENDED:
        raise ValidationFailed(
            {"status": "This clinic is already suspended."}, "This clinic is already suspended."
        )
    was = found.status
    found.status = SUSPENDED
    await session.flush()
    await events.record(
        session,
        organization_id=found.id,
        actor=actor,
        action="platform.suspended",
        resource_type="clinic",
        resource_id=found.id,
        label=found.name,
        changes={"status": [was, SUSPENDED], "reason": reason},
    )
    for member in await PlatformRepository(session).members(found.id):
        await sessions.revoke_all_for(member)
    return found


async def reactivate(
    session: AsyncSession, *, organization_id: uuid.UUID, actor: events.Actor
) -> Organization:
    """Lets a clinic back in, to where it was: running if it had finished
    setting up, still setting up if it had not."""
    found = await _locked_clinic(session, organization_id)
    if found.status != SUSPENDED:
        raise ValidationFailed(
            {"status": "This clinic is not suspended."}, "This clinic is not suspended."
        )
    restored = ACTIVE if found.is_set_up else PENDING
    found.status = restored
    await session.flush()
    await events.record(
        session,
        organization_id=found.id,
        actor=actor,
        action="platform.reactivated",
        resource_type="clinic",
        resource_id=found.id,
        label=found.name,
        changes={"status": [SUSPENDED, restored]},
    )
    return found


async def change_plan(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    plan_id: uuid.UUID,
    actor: events.Actor,
) -> None:
    found = await _locked_clinic(session, organization_id)
    plan = await session.get(SubscriptionPlan, plan_id)
    if plan is None:
        raise ValidationFailed({"plan_id": "That plan does not exist."})
    before = await plans.standing(session, found.id)
    if before.plan.id == plan.id and not before.on_trial:
        raise ValidationFailed(
            {"plan_id": f"The clinic is already on {plan.name}."},
            f"The clinic is already on {plan.name}.",
        )
    await plans.choose(session, found.id, plan)
    was = f"{before.chosen.name} (trial)" if before.on_trial else before.plan.name
    await events.record(
        session,
        organization_id=found.id,
        actor=actor,
        action="platform.plan_changed",
        resource_type="clinic",
        resource_id=found.id,
        label=found.name,
        changes={"plan": [was, plan.name]},
    )


def _plan_out(plan: SubscriptionPlan, clinics: int) -> dict[str, Any]:
    return {
        "id": plan.id,
        "slug": plan.slug,
        "name": plan.name,
        "description": plan.description,
        "price_monthly": plan.price_monthly,
        "limits": {name: plan.limit(name) for name in plans.MEASURES},
        "clinics": clinics,
    }


async def plan_list(session: AsyncSession) -> list[dict[str, Any]]:
    platform = PlatformRepository(session)
    await plans.ensure_plans(session)
    fallback = await plans.plan_named(session, plans.FALLBACK_PLAN)
    held = await platform.clinics_on_plans(fallback.id)
    return [_plan_out(plan, held.get(plan.id, 0)) for plan in await platform.plans()]


async def update_plan(
    session: AsyncSession, *, plan_id: uuid.UUID, body: PlanUpdate
) -> dict[str, Any]:
    result = await session.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id).with_for_update()
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise PlanNotFound
    if body.name is not None:
        plan.name = body.name
    if body.description is not None:
        plan.description = body.description
    if body.price_monthly is not None:
        plan.price_monthly = body.price_monthly
    if body.limits is not None:
        # Replaced whole, so a limit left blank is a limit removed.
        plan.limits = body.limits.model_dump()
    await session.flush()
    fallback = await plans.plan_named(session, plans.FALLBACK_PLAN)
    held = await PlatformRepository(session).clinics_on_plans(fallback.id)
    return _plan_out(plan, held.get(plan.id, 0))


async def metrics(session: AsyncSession) -> dict[str, Any]:
    platform = PlatformRepository(session)
    statuses = await platform.by_status()
    totals = await platform.totals()
    trying = await session.execute(
        select(func.count())
        .select_from(OrganizationSubscription)
        .where(OrganizationSubscription.trial_ends_at > _now())
    )
    catalogue = await plan_list(session)
    return {
        "clinics": sum(statuses.values()),
        "statuses": {
            PENDING: statuses.get(PENDING, 0),
            ACTIVE: statuses.get(ACTIVE, 0),
            SUSPENDED: statuses.get(SUSPENDED, 0),
        },
        **totals,
        "on_trial": int(trying.scalar_one()),
        "signups": [
            {"starts": starts, "clinics": count}
            for starts, count in await platform.signups_by_week(SIGNUP_WEEKS)
        ],
        "plans": [
            {"id": plan["id"], "name": plan["name"], "clinics": plan["clinics"]}
            for plan in catalogue
        ],
    }
