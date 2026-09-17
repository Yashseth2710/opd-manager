"""Password hashing, token minting and the checks that guard both."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
import uuid
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

# Tuned to land near 250ms on the deployment target. Memory cost is the
# parameter that actually hurts an attacker with a GPU; time cost alone does
# not. Re-measure if the function's CPU allocation changes.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

MIN_PASSWORD_LENGTH = 10

# The passwords that turn up first in every credential-stuffing list. Length
# is the real defence, so there are no composition rules to go with this.
_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password12",
        "password123",
        "password1234",
        "passw0rd123",
        "123456789",
        "1234567890",
        "12345678910",
        "qwertyuiop",
        "qwerty12345",
        "1q2w3e4r5t",
        "letmein123",
        "welcome123",
        "admin12345",
        "administrator",
        "iloveyou123",
        "sunshine123",
        "princess123",
        "football123",
        "baseball123",
        "trustno1234",
        "monkey12345",
        "dragon12345",
        "superman123",
        "starwars123",
        "whatever123",
        "computer123",
        "changeme123",
        "secret12345",
        "abcd1234567",
        "asdfghjkl123",
        "zxcvbnm12345",
        "clinic12345",
        "hospital123",
        "doctor12345",
        "welcome@123",
        "admin@12345",
        "india@12345",
        "qwerty@1234",
    }
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(stored: str) -> bool:
    """True once the tuning above has been raised past what this hash used."""
    try:
        return _hasher.check_needs_rehash(stored)
    except (InvalidHashError, ValueError):
        return True


def password_problem(password: str, *, email: str = "", name: str = "") -> str | None:
    """The reason a password is unacceptable, or None. Written as the sentence
    the person reads, so the caller does not rephrase it."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > 128:
        return "Use no more than 128 characters."
    lowered = password.lower().strip()
    if lowered in _COMMON_PASSWORDS:
        return "That password is too widely used. Pick something else."
    if email and lowered == email.lower().split("@")[0]:
        return "Your password cannot be your email address."
    if name and lowered == name.lower().replace(" ", ""):
        return "Your password cannot be your name."
    return None


def new_opaque_token() -> tuple[str, str]:
    """A token to send out, and the hash to keep. The raw value is never
    stored, so a dump of the token store cannot be replayed."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def tokens_match(raw: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_token(raw), stored_hash)


def mint_access_token(
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    role: str,
    permissions: list[str],
    session_id: str,
) -> str:
    """Short-lived and self-contained, so the common request verifies a
    signature instead of querying the database."""
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(organization_id) if organization_id else None,
        "role": role,
        "perms": permissions,
        "sid": session_id,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def read_access_token(token: str) -> dict[str, Any] | None:
    """None for anything we would not act on: expired, tampered, or signed
    with a different key."""
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    return claims
