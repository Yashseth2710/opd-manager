"""Registration, sign-in and account recovery.

Two rules shape most of what follows. A response must never reveal whether an
address has an account, which is why the recovery endpoints acknowledge
everything identically. And a failure must cost an attacker roughly what a
success costs, which is why a miss still pays for a password verification.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import email as mail
from app.core import rate_limit
from app.core.config import get_settings
from app.core.exceptions import (
    AccountLocked,
    AccountSuspended,
    AlreadyExists,
    AppError,
    ClinicSuspended,
    EmailNotVerified,
    InvalidCredentials,
    TokenInvalid,
    ValidationFailed,
)
from app.core.permissions import OWNER
from app.core.security import (
    hash_password,
    mint_access_token,
    needs_rehash,
    password_problem,
    verify_password,
)
from app.db.session import get_factory
from app.models import Organization, User, UserRole
from app.models import notification as kinds
from app.models.organization import SUSPENDED
from app.repositories.users import OrganizationRepository, UserRepository, seed_roles
from app.services import events, plans, sessions

logger = logging.getLogger("opd.auth")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Paid when no account matches, so a miss takes about as long as a hit and
# response time does not become a way to discover which addresses exist.
_DECOY_HASH = hash_password("timing floor, never a real credential")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _seconds_until(moment: dt.datetime | None) -> int:
    if moment is None:
        return LOCKOUT_MINUTES * 60
    return max(int((moment - _now()).total_seconds()), 1)


@dataclass
class SignedIn:
    user: User
    organization: Organization | None
    role: str
    permissions: list[str]
    access_token: str
    refresh_token: str


class ClinicChoiceRequired(AppError):
    """The address has a matching account at more than one clinic.

    Raised only once the password has been proven against each of them, so
    naming the clinics tells the caller nothing they have not established.
    """

    code = "CLINIC_CHOICE_REQUIRED"
    status = 409
    message = "This email is used at more than one clinic. Choose which to sign in to."

    def __init__(self, choices: list[dict[str, str]]) -> None:
        super().__init__()
        self.choices = choices


@dataclass
class Registration:
    session: SignedIn | None = None
    verification_required: bool = False
    email_delivered: bool = False
    choices: list[dict[str, str]] = field(default_factory=list)


async def start_session(session: AsyncSession, user: User) -> SignedIn:
    users = UserRepository(session)
    role, permissions = await users.permissions_for(user)

    organization: Organization | None = None
    if user.organization_id is not None:
        organization = await OrganizationRepository(session).get(user.organization_id)

    refresh_token, opened = await sessions.open_session(user.id)
    access_token = mint_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        role=role,
        permissions=permissions,
        session_id=opened.session_id,
    )

    user.last_login_at = _now()
    user.failed_login_count = 0
    user.locked_until = None
    await session.flush()

    return SignedIn(
        user=user,
        organization=organization,
        role=role,
        permissions=permissions,
        access_token=access_token,
        refresh_token=refresh_token,
    )


async def _send_verification(user: User) -> bool:
    token = await sessions.issue_verification_token(user.id)
    url = f"{get_settings().app_url}/verify-email?token={token}"
    delivery = await mail.send(
        mail.verification_message(to=user.email, name=user.first_name, url=url)
    )
    return delivery.sent


async def register(
    session: AsyncSession,
    *,
    clinic_name: str,
    first_name: str,
    last_name: str,
    email: str,
    password: str,
    phone: str | None,
    timezone: str,
    client_ip: str,
) -> Registration:
    """Creates a clinic and the account that owns it.

    Whoever registers owns the clinic they just made, so they get the
    administrator role. Nothing on this path can produce a platform account:
    those carry no organisation and are created outside the application.
    """
    await rate_limit.check("register", client_ip, rate_limit.REGISTER_PER_IP)

    problem = password_problem(password, email=email, name=f"{first_name}{last_name}")
    if problem:
        raise ValidationFailed({"password": problem})

    organizations = OrganizationRepository(session)
    users = UserRepository(session)

    organization = Organization(
        name=clinic_name,
        slug=await organizations.unique_slug(clinic_name),
        timezone=timezone,
        status="pending",
    )
    session.add(organization)
    await session.flush()

    if await users.email_taken_in(organization.id, email):
        raise AlreadyExists("An account with that email already exists at this clinic.")

    verification_required = get_settings().email_configured

    user = User(
        organization_id=organization.id,
        email=email,
        password_hash=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        status="active",
        # With no provider there is no way to receive a link, so demanding
        # one would lock the first user out of the clinic they just created.
        email_verified_at=None if verification_required else _now(),
    )
    session.add(user)
    await session.flush()

    roles = await seed_roles(session, organization.id)
    session.add(UserRole(user_id=user.id, role_id=roles[OWNER].id))
    await session.flush()
    await plans.start_trial(session, organization.id)

    if verification_required:
        return Registration(
            verification_required=True,
            email_delivered=await _send_verification(user),
        )

    return Registration(session=await start_session(session, user))


async def _count_failure(
    email: str, candidates: list[User], client_ip: str, user_agent: str | None
) -> None:
    """Counts the attempt, and keeps a durable record of it for the clinic.

    The counting itself lives in Redis so a failed attempt costs the same for
    a real address as for one that does not exist. What the clinic keeps is
    written apart from the request, because the request is about to fail and
    everything it wrote goes with it: the attempt in the audit log, and the
    lock on the account row once it actually trips, with a notice to the
    person whose account it is.
    """
    used = await sessions.count_failure(email, MAX_FAILED_ATTEMPTS, LOCKOUT_MINUTES * 60)
    locked = used >= MAX_FAILED_ATTEMPTS
    staff = [user for user in candidates if user.organization_id is not None]
    if not staff:
        return
    async with get_factory()() as apart:
        for candidate in staff:
            organization_id = candidate.organization_id
            if organization_id is None:
                continue
            if locked:
                await apart.execute(
                    update(User)
                    .where(User.id == candidate.id)
                    .values(
                        failed_login_count=used,
                        locked_until=_now() + dt.timedelta(minutes=LOCKOUT_MINUTES),
                    )
                )
            await events.record(
                apart,
                organization_id=organization_id,
                actor=events.Actor(
                    id=None, name="Someone signing in", ip=client_ip, agent=user_agent
                ),
                action="signin.locked" if locked else "signin.failed",
                resource_type="account",
                resource_id=candidate.id,
                label=f"{candidate.full_name} ({candidate.email})",
                changes={"attempt": f"{used} of {MAX_FAILED_ATTEMPTS}"},
            )
            if locked:
                await events.tell(
                    apart,
                    organization_id=organization_id,
                    users=[candidate.id],
                    notice=events.Notice(
                        kind=kinds.ACCOUNT_LOCKED,
                        title="Your account was locked after wrong passwords",
                        body=(
                            f"Somebody got your password wrong {used} times, so signing in "
                            f"was stopped for {LOCKOUT_MINUTES} minutes. If it was not you, "
                            "change your password."
                        ),
                        link=None,
                    ),
                    besides=None,
                )
        await apart.commit()
        await events.deliver(apart)


async def sign_in(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    organization_slug: str | None,
    client_ip: str,
    user_agent: str | None = None,
) -> SignedIn:
    await rate_limit.check("login", client_ip, rate_limit.LOGIN_PER_IP)

    # Checked before anything else touches the database, so a locked address
    # costs an attacker a fast rejection rather than a free password guess.
    locked_for = await sessions.lock_remaining(email)
    if locked_for:
        raise AccountLocked(locked_for)

    users = UserRepository(session)
    candidates = await users.accounts_for_email(email)

    if not candidates:
        # Pay for a hash anyway, so a missing account and a wrong password
        # take about the same time to answer.
        verify_password(password, _DECOY_HASH)
        await _count_failure(email, [], client_ip, user_agent)
        raise InvalidCredentials

    matched = [c for c in candidates if verify_password(password, c.password_hash)]

    if not matched:
        await _count_failure(email, candidates, client_ip, user_agent)
        raise InvalidCredentials

    # Clinics are looked up only once the password is proven, so the failure
    # path makes exactly one query whether or not the address exists.
    organizations = OrganizationRepository(session)
    clinics: dict[str, Organization] = {}
    for candidate in matched:
        if candidate.organization_id is None:
            continue
        clinic = await organizations.get(candidate.organization_id)
        if clinic is not None:
            clinics[str(candidate.id)] = clinic

    if organization_slug:
        matched = [
            candidate
            for candidate in matched
            if str(candidate.id) in clinics
            and clinics[str(candidate.id)].slug == organization_slug
        ]
        if not matched:
            raise InvalidCredentials

    if len(matched) > 1:
        raise ClinicChoiceRequired(
            [
                {"slug": clinics[str(c.id)].slug, "name": clinics[str(c.id)].name}
                for c in matched
                if str(c.id) in clinics
            ]
        )

    user = matched[0]

    # Checked after the password, so the answer only reaches somebody who
    # already holds the credentials and learns nothing new from it.
    # Suspending somebody has to stop them signing back in, not merely end
    # the session they already had.
    if user.status != "active":
        raise AccountSuspended

    held_by = clinics.get(str(user.id))
    if held_by is not None and held_by.status == SUSPENDED:
        raise ClinicSuspended

    if get_settings().email_configured and not user.is_verified:
        raise EmailNotVerified

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    await rate_limit.clear("login", client_ip)
    await sessions.clear_failures(email)
    return await start_session(session, user)


async def request_password_reset(session: AsyncSession, *, email: str) -> None:
    """Acknowledges every address identically.

    The limit is keyed on the address rather than the caller, so one machine
    cannot sweep a list of addresses looking for which ones answer slowly.
    """
    await rate_limit.check("reset", email.lower(), rate_limit.RESET_PER_ADDRESS)

    for user in await UserRepository(session).accounts_for_email(email):
        if user.status != "active":
            continue
        token = await sessions.issue_reset_token(user.id)
        url = f"{get_settings().app_url}/reset-password?token={token}"
        await mail.send(mail.reset_message(to=user.email, name=user.first_name, url=url))


async def complete_password_reset(session: AsyncSession, *, token: str, password: str) -> None:
    # Read the token first and validate against it, so a rejected password
    # leaves the link usable. It is spent only once the reset succeeds.
    user_id = await sessions.peek_reset_token(token)
    if user_id is None:
        raise TokenInvalid

    user = await UserRepository(session).get(user_id)
    if user is None:
        raise TokenInvalid

    problem = password_problem(password, email=user.email, name=user.full_name)
    if problem:
        raise ValidationFailed({"password": problem})

    # Spending it here also settles the race between two requests arriving
    # with the same link: only one of them gets the token back.
    if await sessions.redeem_reset_token(token) is None:
        raise TokenInvalid

    user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    await session.flush()

    # A reset is what someone does when they think the account is
    # compromised, so every session goes, not only the one that asked.
    ended = await sessions.revoke_all_for(user.id)
    logger.info("password reset ended %s session families", ended)


async def verify_email(session: AsyncSession, *, token: str) -> None:
    user_id = await sessions.redeem_verification_token(token)
    if user_id is None:
        raise TokenInvalid

    user = await UserRepository(session).get(user_id)
    if user is None:
        raise TokenInvalid

    if user.email_verified_at is None:
        user.email_verified_at = _now()
        await session.flush()


async def resend_verification(session: AsyncSession, *, email: str) -> None:
    await rate_limit.check("verify", email.lower(), rate_limit.VERIFY_PER_ADDRESS)

    for user in await UserRepository(session).accounts_for_email(email):
        # Sent to the address held on the account, never to one named in the
        # request, so a link cannot be pointed at somebody else's inbox.
        if user.is_verified:
            continue
        await _send_verification(user)
