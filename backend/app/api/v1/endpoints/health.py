"""Liveness endpoint. Reports whether the database is actually reachable
rather than only whether this function booted."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_factory

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    database: dict[str, Any] = {"reachable": False, "server_version": None, "latency_ms": None}

    if settings.database_url:
        started = time.perf_counter()
        try:
            async with get_factory()() as session:
                version = await session.scalar(text("show server_version"))
            database = {
                "reachable": True,
                "server_version": str(version).split(" ")[0] if version else None,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        except Exception:
            # The reason belongs in the logs, never in a public response.
            database["reachable"] = False

    return {
        "status": "ok",
        "environment": settings.environment,
        "version": settings.version,
        "pooled": settings.is_pooled,
        "database": database,
        # Whether a provider is set up at all. The same answer for everyone,
        # so it tells nobody anything about any particular account.
        "email_configured": settings.email_configured,
    }
