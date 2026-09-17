"""Queries for accounts, clinics and the roles that join them."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import CATALOGUE, DEFAULT_ROLES
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

    async def permissions_for(self, user: User) -> tuple[str, list[str]]:
        """The caller's role slug and the permission strings it carries, which
        is what the access token needs to answer questions without a query."""
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
    """
    result = await session.execute(select(Permission.code, Permission.id))
    existing = {code: pid for code, pid in result.all()}

    missing = [code for code in CATALOGUE if code not in existing]
    for code in missing:
        permission = Permission(code=code, description=CATALOGUE[code])
        session.add(permission)
        await session.flush()
        existing[code] = permission.id

    return existing


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
