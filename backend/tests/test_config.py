"""The URL rewrite is the difference between working locally and failing on
deploy, so it is pinned here."""

from __future__ import annotations

from app.core.config import _to_asyncpg

NEON = (  # pragma: allowlist secret
    "postgresql://user:not-a-real-password@ep-example-pooler.ap-southeast-1.aws.neon.tech"
    "/neondb?sslmode=require&channel_binding=require"
)


def test_driver_is_rewritten_for_asyncpg() -> None:
    assert _to_asyncpg(NEON).startswith("postgresql+asyncpg://")


def test_libpq_only_parameters_are_dropped() -> None:
    result = _to_asyncpg(NEON)
    assert "sslmode" not in result
    assert "channel_binding" not in result


def test_host_and_credentials_survive() -> None:
    result = _to_asyncpg(NEON)
    assert "ep-example-pooler.ap-southeast-1.aws.neon.tech" in result
    assert "user:not-a-real-password@" in result


def test_already_rewritten_url_is_untouched() -> None:
    url = "postgresql+asyncpg://user:not-a-real-password@host/db"  # pragma: allowlist secret
    assert _to_asyncpg(url) == url


def test_empty_url_stays_empty() -> None:
    assert _to_asyncpg("") == ""
