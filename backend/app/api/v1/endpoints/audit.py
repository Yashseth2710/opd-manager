"""The clinic's audit log. Read-only: nothing here, or anywhere, edits it."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.core.exceptions import NotFound
from app.models import Organization
from app.schemas.audit import Area, AuditPage
from app.services import audit as service

router = APIRouter(tags=["audit"])


@router.get("/audit-logs")
async def read_log(
    session: DbSession,
    area: Area | None = Query(default=None),
    actor_id: uuid.UUID | None = Query(default=None),
    resource_type: str | None = Query(default=None, max_length=32),
    resource_id: uuid.UUID | None = Query(default=None),
    first: dt.date | None = Query(default=None, alias="from"),
    last: dt.date | None = Query(default=None, alias="to"),
    typed: str | None = Query(default=None, alias="q", max_length=120),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    _: Caller = Depends(requires("audit:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AuditPage:
    """Newest first, narrowed by area, person, record or dates."""
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    found = await service.read(
        session,
        organization_id=organization_id,
        clinic=clinic,
        area=area,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        first=first,
        last=last,
        typed=typed.strip() if typed and typed.strip() else None,
        page=page,
        per_page=per_page,
    )
    return AuditPage.model_validate(found, from_attributes=True)
