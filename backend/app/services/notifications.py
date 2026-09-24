"""One person's notices, and which of them they also want by email."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.core.config import get_settings
from app.core.exceptions import NotFound, ValidationFailed
from app.core.permissions import DOCTOR, OWNER
from app.models import Notification, NotificationPreference
from app.models import notification as kinds

# Each kind as the person choosing is shown it, in the order they see them.
CATALOGUE: dict[str, tuple[str, str]] = {
    kinds.APPOINTMENT_BOOKED: ("New bookings", "Somebody books a patient in with you."),
    kinds.APPOINTMENT_MOVED: (
        "Moved appointments",
        "One of your appointments moves to another time.",
    ),
    kinds.APPOINTMENT_CANCELLED: ("Cancellations", "One of your appointments is cancelled."),
    kinds.LAB_RESULT: ("Lab results", "A result comes in for a test you ordered."),
    kinds.PAID_ONLINE: ("Online payments", "A patient pays a bill from a link."),
    kinds.BILL_VOIDED: ("Voided bills", "Somebody voids a bill that was issued."),
    kinds.STAFF_JOINED: ("New staff", "Somebody accepts an invitation to the clinic."),
    kinds.ROLE_CHANGED: ("Your role", "Your role at the clinic is changed."),
    kinds.ACCOUNT_LOCKED: (
        "Sign-in warnings",
        "Your account is locked after too many wrong passwords.",
    ),
}

PAGE = 20


class NotificationNotFound(NotFound):
    code = "NOTIFICATION_NOT_FOUND"
    message = "That notification is not there any more."


def kinds_for(role: str, permissions: frozenset[str]) -> list[str]:
    """The kinds this person can ever be sent, so they are never offered a
    choice about something that will not reach them."""
    offered: list[str] = []
    if role == DOCTOR:
        offered += [
            kinds.APPOINTMENT_BOOKED,
            kinds.APPOINTMENT_MOVED,
            kinds.APPOINTMENT_CANCELLED,
            kinds.LAB_RESULT,
        ]
    if "billing:read" in permissions:
        offered.append(kinds.PAID_ONLINE)
    if role == OWNER:
        offered += [kinds.BILL_VOIDED, kinds.STAFF_JOINED]
    offered += [kinds.ROLE_CHANGED, kinds.ACCOUNT_LOCKED]
    return offered


def _mine(organization_id: uuid.UUID, user_id: uuid.UUID) -> Any:
    return (Notification.organization_id == organization_id) & (Notification.user_id == user_id)


async def unread(
    session: AsyncSession, *, organization_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    counted = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(_mine(organization_id, user_id))
        .where(Notification.read_at.is_(None))
    )
    return int(counted or 0)


async def listed(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    only_unread: bool,
    before: uuid.UUID | None,
    limit: int = PAGE,
) -> dict[str, Any]:
    """Newest first. Ids sort by when they were made, so the last id of one
    page is where the next one starts."""
    statement = select(Notification).where(_mine(organization_id, user_id))
    if only_unread:
        statement = statement.where(Notification.read_at.is_(None))
    if before is not None:
        statement = statement.where(Notification.id < before)
    found = await session.execute(statement.order_by(Notification.id.desc()).limit(limit + 1))
    rows = list(found.scalars().all())
    return {
        "items": rows[:limit],
        "more": len(rows) > limit,
        "unread": await unread(session, organization_id=organization_id, user_id=user_id),
    }


async def mark_read(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> Notification:
    found = await session.execute(
        select(Notification)
        .where(_mine(organization_id, user_id))
        .where(Notification.id == notification_id)
    )
    notice = found.scalar_one_or_none()
    if notice is None:
        raise NotificationNotFound
    if notice.read_at is None:
        notice.read_at = dt.datetime.now(dt.UTC)
        await session.flush()
    return notice


async def mark_all_read(
    session: AsyncSession, *, organization_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await session.execute(
        update(Notification)
        .where(_mine(organization_id, user_id))
        .where(Notification.read_at.is_(None))
        .values(read_at=dt.datetime.now(dt.UTC))
    )


async def preferences(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    permissions: frozenset[str],
) -> dict[str, Any]:
    found = await session.execute(
        select(NotificationPreference.kind, NotificationPreference.email)
        .where(NotificationPreference.organization_id == organization_id)
        .where(NotificationPreference.user_id == user_id)
    )
    chosen = dict(found.tuples().all())
    return {
        "email_available": get_settings().email_configured,
        "kinds": [
            {
                "kind": kind,
                "label": CATALOGUE[kind][0],
                "description": CATALOGUE[kind][1],
                "email": chosen.get(kind, False),
            }
            for kind in kinds_for(role, permissions)
        ],
    }


async def choose(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    permissions: frozenset[str],
    kind: str,
    email: bool,
) -> dict[str, Any]:
    if kind not in kinds_for(role, permissions):
        raise ValidationFailed(
            {"kind": "Not a notice you can be sent."}, "Choose one of the listed notices."
        )
    await session.execute(
        insert(NotificationPreference)
        .values(
            id=uuid7(),
            organization_id=organization_id,
            user_id=user_id,
            kind=kind,
            email=email,
        )
        .on_conflict_do_update(
            constraint="uq_notification_preference_kind",
            set_={"email": email, "updated_at": func.now()},
        )
    )
    return await preferences(
        session,
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        permissions=permissions,
    )
