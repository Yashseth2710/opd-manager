"""Request dependencies: who is calling, and what they may do.

An access token is checked by its signature alone. That is deliberate: a
Redis or database round trip on every request is real latency on a serverless
function, and the token only lives fifteen minutes, so removing someone takes
effect within that window rather than never.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PermissionDenied, SessionExpired
from app.core.security import read_access_token
from app.db.session import get_factory
from app.models import User
from app.services import events

ACCESS_COOKIE = "opd_access"
REFRESH_COOKIE = "opd_refresh"

# Carries no token and grants nothing. It exists so the web app can tell,
# before rendering, that a session is probably live: the refresh token is
# scoped to the auth endpoints and the access token lasts fifteen minutes,
# so neither is a reliable signal at page level.
SESSION_HINT_COOKIE = "opd_session"


async def db_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request. It commits if the handler returns and
    rolls back if anything escapes, so a half-finished write is never left
    behind by an error."""
    async with get_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            session.info.pop(events.OUTBOX, None)
            await session.rollback()
            raise
        # Email about a change goes out only once the change is certain.
        await events.deliver(session)


# Routes take the session through this rather than Depends(db_session).
# Left to itself, FastAPI finishes a dependency after the response has gone,
# which put the commit behind the answer: the page asked for the record again
# the moment a save came back and could be handed the version from before
# it, and a commit that failed there had already been reported as a success.
# Scoped to the function, the commit happens before anything is sent.
DbSession = Annotated[AsyncSession, Depends(db_session, scope="function")]


@dataclass(frozen=True)
class Caller:
    user_id: uuid.UUID
    organization_id: uuid.UUID | None
    role: str
    permissions: frozenset[str]
    session_id: str

    def may(self, permission: str) -> bool:
        return permission in self.permissions


def client_ip(request: Request) -> str:
    """The address the rate limiter counts against.

    Behind Vercel the socket peer is the proxy, so the first hop in
    X-Forwarded-For is the real caller. It is client-supplied and therefore
    spoofable; it is good enough to slow down a script and nothing more, and
    nothing security-critical is decided from it.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _token_from(request: Request) -> str | None:
    cookie = request.cookies.get(ACCESS_COOKIE)
    if cookie:
        return cookie
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def current_caller(request: Request) -> Caller:
    token = _token_from(request)
    if not token:
        raise SessionExpired("Sign in to continue.")

    claims = read_access_token(token)
    if claims is None:
        raise SessionExpired

    try:
        user_id = uuid.UUID(str(claims.get("sub")))
    except ValueError as exc:
        raise SessionExpired from exc

    organization_id: uuid.UUID | None = None
    raw_org = claims.get("org")
    if raw_org:
        try:
            organization_id = uuid.UUID(str(raw_org))
        except ValueError as exc:
            raise SessionExpired from exc

    permissions = claims.get("perms")
    return Caller(
        user_id=user_id,
        organization_id=organization_id,
        role=str(claims.get("role") or ""),
        permissions=frozenset(permissions if isinstance(permissions, list) else []),
        session_id=str(claims.get("sid") or ""),
    )


async def current_tenant(caller: Caller = Depends(current_caller)) -> uuid.UUID:
    """For routes that touch clinic data. A platform account carries no
    organisation and so has no business on these routes at all."""
    if caller.organization_id is None:
        raise PermissionDenied("This account is not attached to a clinic.")
    return caller.organization_id


def requires(
    permission: str,
) -> Callable[[Caller], Coroutine[Any, Any, Caller]]:
    """Gate a route on one permission string.

    Registering a route that touches clinic data without a dependency that
    resolves the caller is not possible: there is no other way to learn who
    is asking.
    """

    async def dependency(caller: Caller = Depends(current_caller)) -> Caller:
        if not caller.may(permission):
            raise PermissionDenied
        return caller

    return dependency


class Recorder:
    """The audit log and the notices, from inside a route.

    Knows who is asking and from where, so a route says only what happened.
    """

    def __init__(
        self,
        session: AsyncSession,
        caller: Caller,
        organization_id: uuid.UUID,
        ip: str,
        agent: str | None,
    ) -> None:
        self.session = session
        self.caller = caller
        self.organization_id = organization_id
        self._ip = ip
        self._agent = agent
        self._actor: events.Actor | None = None

    async def actor(self) -> events.Actor:
        if self._actor is None:
            user = await self.session.get(User, self.caller.user_id)
            name = user.full_name if user else "Unknown account"
            self._actor = events.Actor(
                id=self.caller.user_id, name=name, ip=self._ip, agent=self._agent
            )
        return self._actor

    async def __call__(
        self,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        label: str | None = None,
        changes: dict[str, Any] | None = None,
    ) -> None:
        await events.record(
            self.session,
            organization_id=self.organization_id,
            actor=await self.actor(),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            label=label,
            changes=changes,
        )

    async def tell(self, users: list[uuid.UUID], notice: events.Notice) -> None:
        await events.tell(
            self.session,
            organization_id=self.organization_id,
            users=users,
            notice=notice,
            besides=self.caller.user_id,
        )


async def recorder(
    request: Request,
    session: DbSession,
    caller: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Recorder:
    return Recorder(
        session, caller, organization_id, client_ip(request), request.headers.get("user-agent")
    )


Trail = Annotated[Recorder, Depends(recorder)]
