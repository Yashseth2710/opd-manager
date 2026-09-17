"""Queries for the people at a clinic, and the invitations that add them.

Invitations go through the scoped repository, so an id belonging to another
clinic reads as absent rather than forbidden. That is the difference between
a 404 and a 403, and 403 would confirm the row exists.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invitation, Role, User, UserRole
from app.models.invitation import PENDING
from app.repositories.base import TenantScopedRepository


class InvitationRepository(TenantScopedRepository[Invitation]):
    model = Invitation

    async def open_for(self, email: str) -> Invitation | None:
        result = await self.session.execute(
            self.query()
            .where(func.lower(Invitation.email) == email.strip().lower())
            .where(Invitation.status == PENDING)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def pending(self) -> list[tuple[Invitation, Role]]:
        result = await self.session.execute(
            self.query()
            .join(Role, Role.id == Invitation.role_id)
            .where(Invitation.status == PENDING)
            .where(Invitation.expires_at > dt.datetime.now(dt.UTC))
            .add_columns(Role)
            .order_by(Invitation.created_at.desc())
        )
        return [(row[0], row[1]) for row in result.all()]


async def by_token_hash(session: AsyncSession, token_hash: str) -> Invitation | None:
    """Looked up without a clinic, because whoever opens an invitation link
    is not signed in and has no clinic yet. The token is the only thing
    identifying it, which is why only its hash is stored."""
    result = await session.execute(
        select(Invitation).where(Invitation.token_hash == token_hash).limit(1)
    )
    return result.scalar_one_or_none()


class StaffRepository:
    """People with an account at one clinic, and the role each one holds."""

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    async def listing(self) -> list[tuple[User, Role | None]]:
        result = await self.session.execute(
            select(User, Role)
            .outerjoin(UserRole, UserRole.user_id == User.id)
            .outerjoin(Role, Role.id == UserRole.role_id)
            .where(User.organization_id == self.organization_id)
            .order_by(User.created_at)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def count_holding(self, role_slug: str) -> int:
        """Used to refuse the change that would leave a clinic with nobody
        able to administer it."""
        result = await self.session.execute(
            select(func.count())
            .select_from(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.organization_id == self.organization_id)
            .where(User.status == "active")
            .where(Role.slug == role_slug)
        )
        return int(result.scalar_one())

    async def role_named(self, slug: str) -> Role | None:
        result = await self.session.execute(
            select(Role)
            .where(Role.organization_id == self.organization_id)
            .where(Role.slug == slug)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def roles(self) -> list[Role]:
        result = await self.session.execute(
            select(Role).where(Role.organization_id == self.organization_id).order_by(Role.name)
        )
        return list(result.scalars().all())

    async def member(self, user_id: uuid.UUID) -> User | None:
        result = await self.session.execute(
            select(User)
            .where(User.id == user_id)
            .where(User.organization_id == self.organization_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def set_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
        existing = await self.session.execute(
            select(UserRole).where(UserRole.user_id == user_id)
        )
        for link in existing.scalars().all():
            await self.session.delete(link)
        await self.session.flush()
        self.session.add(UserRole(user_id=user_id, role_id=role_id))
        await self.session.flush()
