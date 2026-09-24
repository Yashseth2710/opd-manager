"""Each person's own notices. Nobody reads anybody else's, whatever their role."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import Caller, DbSession, current_caller, current_tenant
from app.schemas.notification import (
    NotificationList,
    NotificationOut,
    PreferenceIn,
    Preferences,
    Unread,
)
from app.services import notifications as service

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(
    session: DbSession,
    show: str = Query(default="all", pattern="^(all|unread)$"),
    before: uuid.UUID | None = Query(default=None),
    caller: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> NotificationList:
    found = await service.listed(
        session,
        organization_id=organization_id,
        user_id=caller.user_id,
        only_unread=show == "unread",
        before=before,
    )
    return NotificationList.model_validate(found, from_attributes=True)


@router.get("/notifications/unread")
async def count_unread(
    session: DbSession,
    caller: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Unread:
    """Asked every so often by the bell, so it is one count and nothing else."""
    return Unread(
        unread=await service.unread(
            session, organization_id=organization_id, user_id=caller.user_id
        )
    )


@router.post("/notifications/read-all")
async def read_all(
    session: DbSession,
    caller: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Unread:
    await service.mark_all_read(
        session, organization_id=organization_id, user_id=caller.user_id
    )
    return Unread(unread=0)


@router.get("/notifications/preferences")
async def read_preferences(
    session: DbSession,
    caller: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Preferences:
    found = await service.preferences(
        session,
        organization_id=organization_id,
        user_id=caller.user_id,
        role=caller.role,
        permissions=caller.permissions,
    )
    return Preferences.model_validate(found)


@router.put("/notifications/preferences")
async def choose_preference(
    session: DbSession,
    body: PreferenceIn,
    caller: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Preferences:
    found = await service.choose(
        session,
        organization_id=organization_id,
        user_id=caller.user_id,
        role=caller.role,
        permissions=caller.permissions,
        kind=body.kind,
        email=body.email,
    )
    return Preferences.model_validate(found)


@router.post("/notifications/{notification_id}/read")
async def read_one(
    session: DbSession,
    notification_id: uuid.UUID,
    caller: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> NotificationOut:
    notice = await service.mark_read(
        session,
        organization_id=organization_id,
        user_id=caller.user_id,
        notification_id=notification_id,
    )
    return NotificationOut.model_validate(notice)
