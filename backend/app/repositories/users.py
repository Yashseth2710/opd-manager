"""Queries for accounts, clinics and the roles that join them."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.core.permissions import (
    CATALOGUE,
    DEFAULT_ROLES,
    PLATFORM_PERMISSION,
    PLATFORM_ROLE,
)
from app.models import Organization, Permission, Role, RolePermission, User, UserRole
from app.repositories.base import UnscopedRepository

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_STRIP.sub("-", name.lower()).strip("-")
    return slug[:60] or "clinic"


class UserRepository(UnscopedRepository[User]):
    """Unscoped on purpose: sign-in has to find the account before it knows
    which clinic the caller belongs to. Every query here is by primary key or
    by exact address, never a listing."""

    model = User

    async def accounts_for_email(self, email: str) -> list[User]:
        """Every account on this address.

        Usually one. An address is unique within a clinic, not across the
        platform, so the same person can hold accounts at two clinics and
        sign-in has to decide between them.
        """
        result = await self.session.execute(
            select(User).where(func.lower(User.email) == email.strip().lower()).limit(10)
        )
        return list(result.scalars().all())

    async def email_taken_in(self, organization_id: uuid.UUID, email: str) -> bool:
        result = await self.session.execute(
            select(User.id)
            .where(User.organization_id == organization_id)
            .where(func.lower(User.email) == email.strip().lower())
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def held_by_platform(self, email: str) -> bool:
        """Whether a platform account uses this address. Nobody else may, or
        signing in with it would have to choose between the platform and a
        clinic, and the platform is not somewhere a clinic picks from."""
        result = await self.session.execute(
            select(User.id)
            .where(User.organization_id.is_(None))
            .where(func.lower(User.email) == email.strip().lower())
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def permissions_for(self, user: User) -> tuple[str, list[str]]:
        """The caller's role slug and the permission strings it carries, which
        is what the access token needs to answer questions without a query.

        An account with no clinic is a platform administrator, made from the
        server's command line and never through the application. It holds
        the platform permission and nothing else, so no route that reads a
        clinic's records will ever let it through.
        """
        if user.organization_id is None:
            return PLATFORM_ROLE, [PLATFORM_PERMISSION]
        result = await self.session.execute(
            select(Role.slug, Permission.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(UserRole.user_id == user.id)
        )
        rows = result.all()
        if not rows:
            return "", []
        role_slug = rows[0][0]
        return role_slug, sorted({code for _, code in rows})


class OrganizationRepository(UnscopedRepository[Organization]):
    model = Organization

    async def unique_slug(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        suffix = 2
        while True:
            result = await self.session.execute(
                select(Organization.id).where(Organization.slug == candidate).limit(1)
            )
            if result.scalar_one_or_none() is None:
                return candidate
            candidate = f"{base}-{suffix}"
            suffix += 1


async def ensure_permission_catalogue(session: AsyncSession) -> dict[str, uuid.UUID]:
    """Adds any permission the code knows about that the database does not.

    Called on the path that creates a clinic so a fresh database is usable
    without a separate seeding step, and so adding a permission in code does
    not need a data migration.

    Offered whole and let the database drop what it already has, rather than
    read first and insert the difference. Two clinics signing up at the same
    moment on a fresh deployment both find the catalogue empty, both try to
    write it, and one of them used to lose the race and get a 500 — with a
    half-made clinic rolled back behind it. It is also one round trip rather
    than one per permission, which a cold database notices.
    """
    await session.execute(
        insert(Permission)
        .values(
            [
                {"id": uuid7(), "code": code, "description": description}
                for code, description in CATALOGUE.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=[Permission.code])
    )
    await session.flush()

    result = await session.execute(select(Permission.code, Permission.id))
    return {code: pid for code, pid in result.all()}


async def seed_roles(session: AsyncSession, organization_id: uuid.UUID) -> dict[str, Role]:
    """Gives a new clinic its starting roles, copied from the defaults.

    They are copies rather than references, so a clinic that widens its staff
    role changes nothing for anyone else.
    """
    catalogue = await ensure_permission_catalogue(session)
    roles: dict[str, Role] = {}

    for slug, name, description, codes in DEFAULT_ROLES:
        role = Role(
            organization_id=organization_id,
            slug=slug,
            name=name,
            description=description,
            is_system=True,
        )
        session.add(role)
        await session.flush()
        for code in codes:
            session.add(RolePermission(role_id=role.id, permission_id=catalogue[code]))
        roles[slug] = role

    await session.flush()
    return roles
