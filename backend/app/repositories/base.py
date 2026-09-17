"""Repository bases.

Tenant isolation is enforced here rather than in route handlers, so a query
that forgets it is not something a reviewer has to notice. Reaching past it
requires the unscoped base below, which is named to make that deliberate.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base, TenantRow


class UnscopedRepository[ModelT: Base]:
    """Reaches every clinic's rows. Reserved for platform administration and
    for tables that carry no organisation, such as the permission catalogue."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def query(self) -> Select[tuple[ModelT]]:
        return select(self.model)

    async def get(self, record_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, record_id)

    async def add(self, record: ModelT) -> ModelT:
        self.session.add(record)
        await self.session.flush()
        return record


class TenantScopedRepository[ModelT: TenantRow](UnscopedRepository[ModelT]):
    """Every read is filtered to one clinic and every write is stamped with
    it. A row belonging to another clinic reads as absent, which is why a
    cross-tenant fetch produces a 404 and never a 403."""

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        super().__init__(session)
        self.organization_id = organization_id

    def query(self) -> Select[tuple[ModelT]]:
        return select(self.model).where(self.model.organization_id == self.organization_id)

    async def get(self, record_id: uuid.UUID) -> ModelT | None:
        result = await self.session.execute(self.query().where(self.model.id == record_id))
        return result.scalar_one_or_none()

    async def add(self, record: ModelT) -> ModelT:
        # Set here rather than trusted from the caller, so a request body
        # cannot place a row in someone else's clinic.
        record.organization_id = self.organization_id
        return await super().add(record)

    async def list(self, *conditions: Any, limit: int = 50, offset: int = 0) -> list[ModelT]:
        statement = self.query()
        for condition in conditions:
            statement = statement.where(condition)
        result = await self.session.execute(statement.limit(limit).offset(offset))
        return list(result.scalars().all())
