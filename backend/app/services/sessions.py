"""Refresh token families, and the single-use links sent by email.

An access token is checked by its signature alone, so nothing here runs on a
normal request. Everything in this module is on the sign-in, refresh and
recovery paths, where a Redis round trip is worth what it buys.

Refresh tokens rotate: using one destroys it and issues another. A token that
has already been rotated is never valid again, and presenting one is treated
as a stolen-token replay, which invalidates every token in the same family.
The legitimate holder is signed out too, which is the intended outcome when
the alternative is leaving an attacker with a working session.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from app.core import redis
from app.core.config import get_settings
from app.core.security import hash_token, new_opaque_token

_ACTIVE = "opd:rt"
_SPENT = "opd:rtx"
_FAMILY = "opd:fam"
_RESET = "opd:pwreset"
_VERIFY = "opd:verify"
_USER_FAMILIES = "opd:userfam"

RECOVERY_TOKEN_MINUTES = 30


@dataclass(frozen=True)
class Session:
    user_id: uuid.UUID
    session_id: str
    family_id: str


def _refresh_seconds() -> int:
    return get_settings().refresh_token_days * 24 * 60 * 60


def _encode(session: Session) -> str:
    return f"{session.user_id}:{session.session_id}:{session.family_id}"


def _decode(raw: str) -> Session | None:
    parts = raw.split(":")
    if len(parts) != 3:
        return None
    try:
        return Session(uuid.UUID(parts[0]), parts[1], parts[2])
    except ValueError:
        return None


async def open_session(user_id: uuid.UUID) -> tuple[str, Session]:
    """Starts a new family. Returns the token to hand out and its session."""
    session = Session(
        user_id=user_id,
        session_id=uuid.uuid4().hex,
        family_id=uuid.uuid4().hex,
    )
    raw = await _issue(session)
    await redis.add_to_set(
        f"{_USER_FAMILIES}:{session.user_id}", session.family_id, _refresh_seconds()
    )
    return raw, session


async def _issue(session: Session) -> str:
    raw, digest = new_opaque_token()
    ttl = _refresh_seconds()
    await redis.set_with_expiry(f"{_ACTIVE}:{digest}", _encode(session), ttl)
    await redis.add_to_set(f"{_FAMILY}:{session.family_id}", digest, ttl)
    return raw


class ReplayDetected(Exception):
    """A refresh token was presented twice. The family is already revoked."""


async def rotate(raw_token: str) -> tuple[str, Session] | None:
    """Spends a refresh token and issues its replacement.

    None means the token is unknown or expired. ReplayDetected means it was
    genuinely issued but has already been spent.
    """
    digest = hash_token(raw_token)

    # GETDEL, so two requests arriving together cannot both spend the token.
    stored = await redis.take_once(f"{_ACTIVE}:{digest}")
    if stored is None:
        family = await redis.get(f"{_SPENT}:{digest}")
        if family is not None:
            await revoke_family(family)
            raise ReplayDetected
        return None

    session = _decode(stored)
    if session is None:
        return None

    ttl = _refresh_seconds()
    await redis.set_with_expiry(f"{_SPENT}:{digest}", session.family_id, ttl)
    await redis.drop_from_set(f"{_FAMILY}:{session.family_id}", digest)

    return await _issue(session), session


async def revoke_family(family_id: str) -> None:
    digests = await redis.members(f"{_FAMILY}:{family_id}")
    if digests:
        await redis.delete(*[f"{_ACTIVE}:{d}" for d in digests])
    await redis.delete(f"{_FAMILY}:{family_id}")


async def revoke_all_for(user_id: uuid.UUID) -> int:
    """Ends every session this person has anywhere.

    Used after a password reset, which is what someone does when they believe
    the account is compromised. Signing out only the browser that asked would
    leave the attacker's session running.
    """
    key = f"{_USER_FAMILIES}:{user_id}"
    families = await redis.members(key)
    for family_id in families:
        await revoke_family(family_id)
    await redis.delete(key)
    return len(families)


async def close_session(raw_token: str) -> None:
    """Sign out. Only this device's family goes, not every session the person
    has open elsewhere."""
    digest = hash_token(raw_token)
    stored = await redis.take_once(f"{_ACTIVE}:{digest}")
    if stored is None:
        return
    session = _decode(stored)
    if session is not None:
        await revoke_family(session.family_id)


async def _store_recovery(prefix: str, user_id: uuid.UUID) -> str:
    raw, digest = new_opaque_token()
    await redis.set_with_expiry(f"{prefix}:{digest}", str(user_id), RECOVERY_TOKEN_MINUTES * 60)
    return raw


async def _peek_recovery(prefix: str, raw_token: str) -> uuid.UUID | None:
    """Reads a recovery token without spending it.

    Used to check who a link belongs to before validating the new password,
    so a rejected password does not burn the link and leave the person with
    nothing to retry.
    """
    stored = await redis.get(f"{prefix}:{hash_token(raw_token)}")
    if stored is None:
        return None
    try:
        return uuid.UUID(stored)
    except ValueError:
        return None


async def _redeem_recovery(prefix: str, raw_token: str) -> uuid.UUID | None:
    # GETDEL again: the token stops existing the moment it is redeemed, so a
    # second attempt with the same link finds nothing.
    stored = await redis.take_once(f"{prefix}:{hash_token(raw_token)}")
    if stored is None:
        return None
    try:
        return uuid.UUID(stored)
    except ValueError:
        return None


async def issue_reset_token(user_id: uuid.UUID) -> str:
    return await _store_recovery(_RESET, user_id)


async def peek_reset_token(raw_token: str) -> uuid.UUID | None:
    return await _peek_recovery(_RESET, raw_token)


async def redeem_reset_token(raw_token: str) -> uuid.UUID | None:
    return await _redeem_recovery(_RESET, raw_token)


async def issue_verification_token(user_id: uuid.UUID) -> str:
    return await _store_recovery(_VERIFY, user_id)


async def redeem_verification_token(raw_token: str) -> uuid.UUID | None:
    return await _redeem_recovery(_VERIFY, raw_token)


def refresh_cookie_expiry() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(seconds=_refresh_seconds())


_LOCKOUT = "opd:lock"


async def count_failure(email: str, attempts_allowed: int, lock_seconds: int) -> int:
    """Counts a failed sign-in against an address and returns the tally.

    Kept in Redis rather than on the user row so the cost is identical
    whether or not the address has an account. A database write here would
    happen only for real accounts, and the extra round trip would make the
    response measurably slower for them, which is exactly the signal the
    identical error message exists to hide.
    """
    key = f"{_LOCKOUT}:{email.lower()}"
    used = await redis.increment_within(key, lock_seconds)
    if used >= attempts_allowed:
        await redis.set_with_expiry(f"{key}:until", "1", lock_seconds)
    return used


async def lock_remaining(email: str) -> int:
    """Seconds left on a lockout, or zero if the address is not locked."""
    return await redis.seconds_remaining(f"{_LOCKOUT}:{email.lower()}:until")


async def clear_failures(email: str) -> None:
    key = f"{_LOCKOUT}:{email.lower()}"
    await redis.delete(key, f"{key}:until")
