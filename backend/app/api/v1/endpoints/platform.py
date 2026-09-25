"""The platform's own routes. None of them reads a clinic's records: they
see clinics, plans and counts, and nothing a patient told a doctor."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import Caller, DbSession, client_ip, platform_caller
from app.core.exceptions import SessionExpired
from app.repositories.users import UserRepository
from app.schemas.platform import (
    ClinicDetail,
    ClinicPage,
    ClinicStatus,
    Metrics,
    PlanChoice,
    PlanOut,
    PlanUpdate,
    Suspension,
)
from app.services import events
from app.services import platform as service

router = APIRouter(prefix="/platform", tags=["platform"])


async def _actor(request: Request, session: DbSession, caller: Caller) -> events.Actor:
    user = await UserRepository(session).get(caller.user_id)
    if user is None or user.status != "active":
        raise SessionExpired
    return events.Actor(
        id=user.id,
        # Read in a clinic's own log, where it has to say plainly that this
        # was done from outside the clinic.
        name=f"{user.full_name} (platform)",
        ip=client_ip(request),
        agent=request.headers.get("user-agent"),
    )


@router.get("/metrics")
async def metrics(
    session: DbSession,
    _: Caller = Depends(platform_caller),
) -> Metrics:
    return Metrics.model_validate(await service.metrics(session))


@router.get("/organizations")
async def list_clinics(
    session: DbSession,
    typed: str | None = Query(default=None, alias="q", max_length=100),
    status: ClinicStatus | None = None,
    plan_id: uuid.UUID | None = None,
    sort: Literal["-created_at", "created_at", "name"] = "-created_at",
    page: int = Query(default=1, ge=1, le=10_000),
    per_page: int = Query(default=25, ge=1, le=100),
    _: Caller = Depends(platform_caller),
) -> ClinicPage:
    return ClinicPage.model_validate(
        await service.clinics(
            session,
            typed=typed,
            status=status,
            plan_id=plan_id,
            sort=sort,
            page=page,
            per_page=per_page,
        )
    )


@router.get("/organizations/{organization_id}")
async def read_clinic(
    session: DbSession,
    organization_id: uuid.UUID,
    _: Caller = Depends(platform_caller),
) -> ClinicDetail:
    return ClinicDetail.model_validate(await service.clinic(session, organization_id))


@router.post("/organizations/{organization_id}/suspend")
async def suspend_clinic(
    request: Request,
    session: DbSession,
    organization_id: uuid.UUID,
    body: Suspension,
    caller: Caller = Depends(platform_caller),
) -> ClinicDetail:
    actor = await _actor(request, session, caller)
    await service.suspend(
        session, organization_id=organization_id, reason=body.reason, actor=actor
    )
    return ClinicDetail.model_validate(await service.clinic(session, organization_id))


@router.post("/organizations/{organization_id}/reactivate")
async def reactivate_clinic(
    request: Request,
    session: DbSession,
    organization_id: uuid.UUID,
    caller: Caller = Depends(platform_caller),
) -> ClinicDetail:
    actor = await _actor(request, session, caller)
    await service.reactivate(session, organization_id=organization_id, actor=actor)
    return ClinicDetail.model_validate(await service.clinic(session, organization_id))


@router.put("/organizations/{organization_id}/plan")
async def choose_plan(
    request: Request,
    session: DbSession,
    organization_id: uuid.UUID,
    body: PlanChoice,
    caller: Caller = Depends(platform_caller),
) -> ClinicDetail:
    actor = await _actor(request, session, caller)
    await service.change_plan(
        session, organization_id=organization_id, plan_id=body.plan_id, actor=actor
    )
    return ClinicDetail.model_validate(await service.clinic(session, organization_id))


@router.get("/plans")
async def list_plans(
    session: DbSession,
    _: Caller = Depends(platform_caller),
) -> list[PlanOut]:
    return [PlanOut.model_validate(plan) for plan in await service.plan_list(session)]


@router.patch("/plans/{plan_id}")
async def update_plan(
    session: DbSession,
    plan_id: uuid.UUID,
    body: PlanUpdate,
    _: Caller = Depends(platform_caller),
) -> PlanOut:
    updated = await service.update_plan(session, plan_id=plan_id, body=body)
    return PlanOut.model_validate(updated)
