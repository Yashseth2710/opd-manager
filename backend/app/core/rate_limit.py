"""Fixed-window counters for the endpoints an attacker would hammer.

Redis holds the counts, so the limit is shared across every function instance
rather than being per-process and trivially sidestepped.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass

from app.core import redis
from app.core.exceptions import RateLimited

logger = logging.getLogger("opd.ratelimit")


@dataclass(frozen=True)
class Limit:
    attempts: int
    seconds: int


# Sourced from the limits table in the security notes.
LOGIN_PER_IP = Limit(attempts=10, seconds=15 * 60)
RESET_PER_ADDRESS = Limit(attempts=3, seconds=60 * 60)
VERIFY_PER_ADDRESS = Limit(attempts=3, seconds=60 * 60)
REGISTER_PER_IP = Limit(attempts=5, seconds=60 * 60)


async def check(bucket: str, identifier: str, limit: Limit) -> None:
    """Counts one attempt and raises once the window is full.

    If Redis is unreachable the request is allowed through. Rate limiting is
    a brake, not an authorisation check, and failing closed here would take
    sign-in down entirely for an outage in a secondary service.
    """
    key = f"opd:rl:{bucket}:{identifier}"
    try:
        used = await redis.increment_within(key, limit.seconds)
    except redis.RedisUnavailable:
        logger.error("rate limit skipped, store unreachable: %s", bucket)
        return

    if used > limit.attempts:
        retry_after = await redis.seconds_remaining(key)
        raise RateLimited(retry_after or limit.seconds)


async def clear(bucket: str, identifier: str) -> None:
    """Called after a success, so a legitimate sign-in does not spend the
    window that a later mistyped password will need."""
    with contextlib.suppress(redis.RedisUnavailable):
        await redis.delete(f"opd:rl:{bucket}:{identifier}")
