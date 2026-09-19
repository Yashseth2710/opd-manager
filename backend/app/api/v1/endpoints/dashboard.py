"""The first page after signing in."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.core.exceptions import NotFound
from app.models import Organization
from app.schemas.dashboard import Today
from app.services import appointments
from app.services import dashboard as service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary")
async def read_summary(
    session: DbSession,
    caller: Caller = Depends(requires("appointment:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Today:
    """Today at the clinic, or a doctor's own day when a doctor asks."""
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    reach = await appointments.reach_of(
        session, organization_id=organization_id, user_id=caller.user_id, role=caller.role
    )
    found = await service.today(
        session, organization_id=organization_id, clinic=clinic, reach=reach
    )
    return Today.model_validate(found)
