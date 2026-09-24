"""Something happened at the clinic: write it down, and tell whoever needs to know.

Both halves write into the session the change itself was made in. An entry in
the log and a notice in somebody's list therefore exist only if the change
does; a request that fails halfway leaves neither behind. Email is the one
thing that cannot be taken back, so it waits in the session until the commit
has gone through and only then is sent.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import email as mail
from app.core.config import get_settings
from app.db.session import get_factory
from app.models import (
    AuditEntry,
    Doctor,
    Notification,
    NotificationPreference,
    Patient,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.models import notification as kinds

logger = logging.getLogger("opd.events")

OUTBOX = "outbox"


@dataclass(frozen=True)
class Actor:
    id: uuid.UUID | None
    name: str
    ip: str | None = None
    agent: str | None = None


# Whoever pays from a link has no account and is not a member of staff.
PATIENT_ONLINE = Actor(id=None, name="Patient (online)")


@dataclass(frozen=True)
class Notice:
    kind: str
    title: str
    body: str | None = None
    link: str | None = None


@dataclass(frozen=True)
class _Letter:
    notification_id: uuid.UUID
    to: str
    notice: Notice


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, list | tuple):
        return [_plain(each) for each in value]
    if isinstance(value, dict):
        return {str(key): _plain(each) for key, each in value.items()}
    return str(value)


def snapshot(record: Any, fields: Iterable[str]) -> dict[str, Any]:
    return {name: _plain(getattr(record, name)) for name in fields}


def difference(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any] | None:
    """What moved between two snapshots, as {"field": [was, now]}."""
    moved = {
        name: [before.get(name), after.get(name)]
        for name in after
        if before.get(name) != after.get(name)
    }
    return moved or None


async def record(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Actor,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    label: str | None = None,
    changes: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEntry(
            organization_id=organization_id,
            actor_id=actor.id,
            actor_name=actor.name[:160],
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_label=label[:200] if label else None,
            changes=_plain(changes) if changes else None,
            ip_address=actor.ip[:64] if actor.ip else None,
            user_agent=actor.agent[:300] if actor.agent else None,
        )
    )
    await session.flush()


async def record_apart(
    *,
    organization_id: uuid.UUID,
    actor: Actor,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    label: str | None = None,
    changes: dict[str, Any] | None = None,
    notify: tuple[uuid.UUID, Notice] | None = None,
) -> None:
    """For something worth keeping about a request that is about to fail.

    A wrong password ends in an error, and the error rolls the request back,
    so the entry has to be written in a transaction of its own.
    """
    async with get_factory()() as apart:
        await record(
            apart,
            organization_id=organization_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            label=label,
            changes=changes,
        )
        if notify is not None:
            user_id, notice = notify
            await tell(
                apart,
                organization_id=organization_id,
                users=[user_id],
                notice=notice,
                besides=None,
            )
        await apart.commit()
        await deliver(apart)


# --- Who hears about it -----------------------------------------------------------


async def doctor_account(
    session: AsyncSession, organization_id: uuid.UUID, doctor_id: uuid.UUID
) -> list[uuid.UUID]:
    found = await session.execute(
        select(Doctor.user_id)
        .where(Doctor.organization_id == organization_id)
        .where(Doctor.id == doctor_id)
    )
    user_id = found.scalar_one_or_none()
    return [user_id] if user_id else []


async def holding(
    session: AsyncSession, organization_id: uuid.UUID, permission: str
) -> list[uuid.UUID]:
    """Everyone at the clinic whose role carries the permission."""
    found = await session.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(User.organization_id == organization_id)
        .where(Permission.code == permission)
    )
    return list(dict.fromkeys(found.scalars().all()))


async def in_role(
    session: AsyncSession, organization_id: uuid.UUID, slug: str
) -> list[uuid.UUID]:
    found = await session.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.organization_id == organization_id)
        .where(Role.slug == slug)
    )
    return list(found.scalars().all())


async def tell(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    users: Iterable[uuid.UUID],
    notice: Notice,
    besides: uuid.UUID | None,
) -> None:
    """Leaves the notice with each of them, other than whoever caused it.

    Only active accounts at this clinic receive anything, whatever list the
    caller worked out: somebody suspended, or at another clinic, hears
    nothing.
    """
    asked = {user_id for user_id in users if user_id != besides}
    if not asked:
        return
    found = await session.execute(
        select(User.id, User.email)
        .where(User.organization_id == organization_id)
        .where(User.status == "active")
        .where(User.id.in_(asked))
    )
    reachable = dict(found.tuples().all())
    if not reachable:
        return

    wanting = await session.execute(
        select(NotificationPreference.user_id)
        .where(NotificationPreference.user_id.in_(reachable))
        .where(NotificationPreference.kind == notice.kind)
        .where(NotificationPreference.email.is_(True))
    )
    by_email = set(wanting.scalars().all())

    letters: list[_Letter] = session.info.setdefault(OUTBOX, [])
    for user_id, address in reachable.items():
        written = Notification(
            organization_id=organization_id,
            user_id=user_id,
            kind=notice.kind,
            title=notice.title[:160],
            body=notice.body[:400] if notice.body else None,
            link=notice.link,
            channel=kinds.EMAIL if user_id in by_email else kinds.IN_APP,
        )
        session.add(written)
        await session.flush()
        if user_id in by_email:
            letters.append(_Letter(written.id, address, notice))


async def deliver(session: AsyncSession) -> None:
    """Sends what the committed transaction left waiting.

    Called only after the commit. A provider that is down costs the email and
    nothing else: the notice is already in the app, and the request that
    caused it has already succeeded.
    """
    letters: list[_Letter] = session.info.pop(OUTBOX, [])
    if not letters:
        return
    base = get_settings().app_url.rstrip("/")
    sent: list[uuid.UUID] = []
    for letter in letters:
        notice = letter.notice
        try:
            delivery = await mail.send(
                mail.Message(
                    to=letter.to,
                    subject=notice.title,
                    heading=notice.title,
                    body=notice.body or "",
                    action_label="Open in OPD Manager",
                    action_url=f"{base}{notice.link or '/notifications'}",
                )
            )
        except Exception:
            logger.exception("a notice could not be emailed: %s", notice.kind)
            continue
        if delivery.sent:
            sent.append(letter.notification_id)
    if not sent:
        return
    try:
        await session.execute(
            update(Notification)
            .where(Notification.id.in_(sent))
            .values(sent_at=dt.datetime.now(dt.UTC))
        )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("sent notices could not be marked as sent")


async def patient_named(
    session: AsyncSession, organization_id: uuid.UUID, patient_id: uuid.UUID
) -> str | None:
    """How a patient reads in the log: their name and their number."""
    found = await session.execute(
        select(Patient.first_name, Patient.last_name, Patient.patient_number)
        .where(Patient.organization_id == organization_id)
        .where(Patient.id == patient_id)
    )
    row = found.one_or_none()
    if row is None:
        return None
    first, last, number = row
    return f"{first} {last}".strip() + f" ({number})"
