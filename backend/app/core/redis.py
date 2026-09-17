"""Redis over Upstash's REST interface.

A serverless function cannot keep a TCP connection open between invocations,
so commands go over HTTP. Every key this module writes carries an expiry:
nothing here is permanent, and Redis removes it without a cleanup job.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("opd.redis")

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            base_url=settings.upstash_redis_rest_url,
            headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}"},
            timeout=httpx.Timeout(5.0, connect=3.0),
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class RedisUnavailable(RuntimeError):
    """Raised when the token store cannot be reached.

    Callers treat this as a hard failure rather than carrying on. A sign-in
    that cannot record a session, or a reset that cannot store its token,
    must not report success.
    """


async def command(*args: Any) -> Any:
    settings = get_settings()
    if not settings.redis_configured:
        raise RedisUnavailable("Redis is not configured")

    try:
        response = await _http().post("/", json=[str(a) for a in args])
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # The command can name a key, so it is never logged with its value.
        logger.error("redis command failed: %s", args[0] if args else "?")
        raise RedisUnavailable(str(exc)) from exc

    payload = response.json()
    if isinstance(payload, dict) and "error" in payload:
        logger.error("redis rejected a command: %s", args[0] if args else "?")
        raise RedisUnavailable(str(payload["error"]))
    return payload.get("result") if isinstance(payload, dict) else payload


async def set_with_expiry(key: str, value: str, seconds: int) -> None:
    await command("SET", key, value, "EX", seconds)


async def get(key: str) -> str | None:
    result = await command("GET", key)
    return None if result is None else str(result)


async def delete(*keys: str) -> int:
    if not keys:
        return 0
    return int(await command("DEL", *keys) or 0)


async def take_once(key: str) -> str | None:
    """Read a value and remove it in the same breath, so a single-use token
    cannot be redeemed twice by two requests arriving together."""
    result = await command("GETDEL", key)
    return None if result is None else str(result)


async def increment_within(key: str, seconds: int) -> int:
    """Count one hit against a window, returning the running total. The expiry
    is set only on the first hit so the window does not slide forward with
    every attempt, which would let a steady drip of requests never reset."""
    count = int(await command("INCR", key) or 0)
    if count == 1:
        await command("EXPIRE", key, seconds)
    return count


async def seconds_remaining(key: str) -> int:
    ttl = int(await command("TTL", key) or 0)
    return max(ttl, 0)


async def members(key: str) -> list[str]:
    result = await command("SMEMBERS", key)
    return [str(item) for item in result] if isinstance(result, list) else []


async def add_to_set(key: str, value: str, expire_seconds: int) -> None:
    await command("SADD", key, value)
    await command("EXPIRE", key, expire_seconds)


async def drop_from_set(key: str, value: str) -> None:
    await command("SREM", key, value)
