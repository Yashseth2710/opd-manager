"""Reading the audit log. There is no way to change it from here."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Select, func, or_, select

from app.models import AuditEntry
from app.repositories.base import TenantScopedRepository
from app.repositories.prescriptions import _as_typed


class AuditRepository(TenantScopedRepository[AuditEntry]):
    model = AuditEntry

    def _filtered(
        self,
        *,
        types: tuple[str, ...] | None,
        actor_id: uuid.UUID | None,
        resource_type: str | None,
        resource_id: uuid.UUID | None,
        since: dt.datetime | None,
        until: dt.datetime | None,
        typed: str | None,
    ) -> Select[tuple[AuditEntry]]:
        statement = self.query()
        if types:
            statement = statement.where(AuditEntry.resource_type.in_(types))
        if actor_id:
            statement = statement.where(AuditEntry.actor_id == actor_id)
        if resource_type:
            statement = statement.where(AuditEntry.resource_type == resource_type)
        if resource_id:
            statement = statement.where(AuditEntry.resource_id == resource_id)
        if since:
            statement = statement.where(AuditEntry.created_at >= since)
        if until:
            statement = statement.where(AuditEntry.created_at < until)
        if typed:
            pattern = f"%{_as_typed(typed)}%"
            statement = statement.where(
                or_(
                    AuditEntry.actor_name.ilike(pattern, escape="\\"),
                    AuditEntry.resource_label.ilike(pattern, escape="\\"),
                )
            )
        return statement

    async def page(
        self,
        *,
        types: tuple[str, ...] | None,
        actor_id: uuid.UUID | None,
        resource_type: str | None,
        resource_id: uuid.UUID | None,
        since: dt.datetime | None,
        until: dt.datetime | None,
        typed: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditEntry], int]:
        statement = self._filtered(
            types=types,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            since=since,
            until=until,
            typed=typed,
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        found = await self.session.execute(
            statement.order_by(AuditEntry.created_at.desc(), AuditEntry.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(found.scalars().all()), int(total or 0)

    async def actors(self) -> list[tuple[uuid.UUID, str]]:
        """Everyone who appears in the log, by the name they last appeared
        under, for choosing whose actions to look at."""
        latest = (
            select(
                AuditEntry.actor_id,
                AuditEntry.actor_name,
                func.row_number()
                .over(
                    partition_by=AuditEntry.actor_id,
                    order_by=AuditEntry.created_at.desc(),
                )
                .label("place"),
            )
            .where(AuditEntry.organization_id == self.organization_id)
            .where(AuditEntry.actor_id.is_not(None))
            .subquery()
        )
        found = await self.session.execute(
            select(latest.c.actor_id, latest.c.actor_name)
            .where(latest.c.place == 1)
            .order_by(latest.c.actor_name)
        )
        return [(row[0], row[1]) for row in found.all()]
