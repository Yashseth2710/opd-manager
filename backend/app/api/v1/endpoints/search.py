"""The search box. Reading only, so nothing here is written to the audit log."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import Caller, DbSession, current_caller, current_tenant
from app.core.exceptions import NotFound
from app.models import Organization
from app.schemas.search import Found
from app.services import search as service

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(
    session: DbSession,
    typed: str = Query(default="", alias="q", max_length=100),
    caller: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Found:
    """Up to five of each kind the caller's role may open, closest first."""
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    found = await service.find(
        session,
        organization_id=organization_id,
        clinic=clinic,
        user_id=caller.user_id,
        role=caller.role,
        permissions=caller.permissions,
        typed=typed,
    )
    return Found.model_validate(found, from_attributes=True)
