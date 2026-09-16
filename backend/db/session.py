"""Database engine and session handling.

The API runs as a serverless function, so nothing here is a long-lived
process. Connection pooling happens in PgBouncer ahead of us, not in
SQLAlchemy, which is why this uses NullPool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from backend.core.config import get_settings

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not set")
        _engine = create_async_engine(
            settings.database_url,
            poolclass=NullPool,
            connect_args=settings.connect_args,
            echo=False,
        )
    return _engine


def get_factory() -> async_sessionmaker[AsyncSession]:
    global _factory
    if _factory is None:
        _factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_factory()() as session:
        yield session
