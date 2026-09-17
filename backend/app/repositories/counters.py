"""Allocation of the per-clinic numbers that people read out loud."""

from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.counter import TenantCounter


async def next_in_sequence(
    session: AsyncSession, organization_id: uuid.UUID, counter: str
) -> int:
    """Takes the next number for one clinic's counter.

    A single statement, so it holds under two receptionists pressing Register
    at the same instant: the second waits on the row lock and is handed the
    number after the first, rather than both reading the same count.
    """
    statement = (
        insert(TenantCounter)
        .values(organization_id=organization_id, counter=counter, value=1)
        .on_conflict_do_update(
            index_elements=[TenantCounter.organization_id, TenantCounter.counter],
            set_={"value": TenantCounter.value + 1},
        )
        .returning(TenantCounter.value)
    )
    result = await session.execute(statement)
    return int(result.scalar_one())
