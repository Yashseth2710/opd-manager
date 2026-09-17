"""Clinic setup and the staff who work there.

Two rules run through this. A clinic must never be left without somebody who
can administer it, and an invitation must never be a way to learn about a
clinic you were not invited to.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import email as mail
from app.core import rate_limit
from app.core.config import get_settings
from app.core.exceptions import AlreadyExists, AppError, NotFound, ValidationFailed
from app.core.permissions import OWNER
from app.core.security import hash_password, hash_token, new_opaque_token, password_problem
from app.models import Invitation, Organization, User
from app.models.invitation import ACCEPTED, EXPIRY_DAYS, PENDING, REVOKED
from app.repositories.staff import InvitationRepository, StaffRepository, by_token_hash
from app.repositories.users import UserRepository
from app.schemas.clinic import Address, ClinicSettingsUpdate, ClinicUpdate

logger = logging.getLogger("opd.clinic")


class LastAdministrator(AppError):
    """Refuses the change that would leave nobody able to run the clinic."""

    code = "LAST_ADMINISTRATOR"
    status = 409
    message = "This is the only administrator. Give someone else the role first."


class InvitationUnusable(AppError):
    code = "INVITATION_INVALID"
    status = 400
    message = "That invitation is not valid. It may have expired or already been used."


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _as_money(value: Decimal) -> str:
    return f"{value:.2f}"


async def update_clinic(
    session: AsyncSession, clinic: Organization, changes: ClinicUpdate
) -> Organization:
    supplied = changes.model_dump(exclude_unset=True, exclude_none=True)

    address = supplied.pop("address", None)
    if address is not None:
        clinic.address = Address.model_validate(address).model_dump()

    for field, value in supplied.items():
        setattr(clinic, field, value)

    await session.flush()
    return clinic


async def update_settings(
    session: AsyncSession, clinic: Organization, changes: ClinicSettingsUpdate
) -> Organization:
    supplied = changes.model_dump(exclude_unset=True, exclude_none=True)

    merged: dict[str, Any] = dict(clinic.settings or {})
    for field, value in supplied.items():
        merged[field] = _as_money(value) if isinstance(value, Decimal) else value

    # Replaced rather than mutated: SQLAlchemy does not notice a dictionary
    # changed in place, and the update would silently never be written.
    clinic.settings = merged
    await session.flush()
    return clinic


async def finish_setup(session: AsyncSession, clinic: Organization) -> Organization:
    """Marks the clinic ready and opens it for business.

    Refuses while the details a clinic cannot operate without are missing,
    rather than letting someone skip past and find out later.
    """
    missing: dict[str, str] = {}
    if not (clinic.phone or "").strip():
        missing["phone"] = "A contact number is needed."
    address = clinic.address or {}
    if not str(address.get("line1", "")).strip():
        missing["address"] = "A street address is needed."
    if not str(address.get("city", "")).strip():
        missing["city"] = "A city is needed."
    if missing:
        raise ValidationFailed(missing)

    if clinic.onboarding_completed_at is None:
        clinic.onboarding_completed_at = _now()
    clinic.status = "active"
    await session.flush()
    return clinic


@dataclass
class Invited:
    invitation: Invitation
    delivered: bool


async def invite(
    session: AsyncSession,
    *,
    clinic: Organization,
    inviter: User,
    email: str,
    first_name: str,
    last_name: str,
    role_slug: str,
) -> Invited:
    staff = StaffRepository(session, clinic.id)

    role = await staff.role_named(role_slug)
    if role is None:
        raise ValidationFailed({"role_slug": "That role does not exist at this clinic."})

    users = UserRepository(session)
    if await users.email_taken_in(clinic.id, email):
        raise AlreadyExists("Somebody with that email already works here.")

    invitations = InvitationRepository(session, clinic.id)
    if await invitations.open_for(email) is not None:
        raise AlreadyExists("That person already has an invitation waiting.")

    raw, digest = new_opaque_token()
    invitation = Invitation(
        email=email,
        first_name=first_name,
        last_name=last_name,
        role_id=role.id,
        invited_by_id=inviter.id,
        invited_by_name=inviter.full_name,
        token_hash=digest,
        status=PENDING,
        expires_at=_now() + dt.timedelta(days=EXPIRY_DAYS),
    )
    # Stamped by the repository, never taken from the request.
    await invitations.add(invitation)

    url = f"{get_settings().app_url}/join?token={raw}"
    delivery = await mail.send(
        mail.invitation_message(
            to=email,
            name=first_name,
            clinic=clinic.name,
            role=role.name,
            inviter=inviter.full_name,
            url=url,
        )
    )
    return Invited(invitation=invitation, delivered=delivery.sent)


async def revoke(session: AsyncSession, clinic: Organization, invitation_id: uuid.UUID) -> None:
    invitations = InvitationRepository(session, clinic.id)
    invitation = await invitations.get(invitation_id)
    # A different clinic's invitation reads as absent, never as forbidden.
    if invitation is None or invitation.status != PENDING:
        raise NotFound("That invitation could not be found.")

    invitation.status = REVOKED
    await session.flush()


async def preview(session: AsyncSession, token: str) -> tuple[Invitation, Organization, str]:
    invitation = await by_token_hash(session, hash_token(token))
    if invitation is None or not invitation.is_open:
        raise InvitationUnusable

    clinic = await session.get(Organization, invitation.organization_id)
    if clinic is None:
        raise InvitationUnusable

    from app.models import Role

    role = await session.get(Role, invitation.role_id)
    return invitation, clinic, role.name if role else ""


async def accept(session: AsyncSession, *, token: str, password: str, client_ip: str) -> User:
    """Turns an invitation into an account at the clinic that sent it.

    The clinic and role come from the invitation, never from the request, so
    holding a link cannot be turned into a role nobody granted.
    """
    await rate_limit.check("accept", client_ip, rate_limit.REGISTER_PER_IP)

    invitation = await by_token_hash(session, hash_token(token))
    if invitation is None or not invitation.is_open:
        raise InvitationUnusable

    problem = password_problem(password, email=invitation.email)
    if problem:
        raise ValidationFailed({"password": problem})

    users = UserRepository(session)
    if await users.email_taken_in(invitation.organization_id, invitation.email):
        invitation.status = ACCEPTED
        invitation.accepted_at = _now()
        await session.flush()
        raise AlreadyExists("An account with that email already exists at this clinic.")

    user = User(
        organization_id=invitation.organization_id,
        email=invitation.email,
        password_hash=hash_password(password),
        first_name=invitation.first_name or invitation.email.split("@")[0][:80],
        last_name=invitation.last_name,
        status="active",
        # Accepting proves they read mail at that address, which is the same
        # thing confirmation establishes.
        email_verified_at=_now(),
    )
    session.add(user)
    await session.flush()

    from app.models import UserRole

    session.add(UserRole(user_id=user.id, role_id=invitation.role_id))

    invitation.status = ACCEPTED
    invitation.accepted_at = _now()
    await session.flush()
    return user


async def change_role(
    session: AsyncSession,
    *,
    clinic: Organization,
    actor: User,
    member_id: uuid.UUID,
    role_slug: str,
) -> User:
    staff = StaffRepository(session, clinic.id)

    member = await staff.member(member_id)
    if member is None:
        raise NotFound("That person could not be found.")

    role = await staff.role_named(role_slug)
    if role is None:
        raise ValidationFailed({"role_slug": "That role does not exist at this clinic."})

    current = await staff.role_named(OWNER)
    if current is not None and role.slug != OWNER:
        held = await staff.count_holding(OWNER)
        members_role = next(
            (r for u, r in await staff.listing() if u.id == member_id and r is not None), None
        )
        if held <= 1 and members_role is not None and members_role.slug == OWNER:
            raise LastAdministrator

    await staff.set_role(member_id, role.id)
    logger.info("role changed by %s", actor.id)
    return member


async def set_member_status(
    session: AsyncSession,
    *,
    clinic: Organization,
    actor: User,
    member_id: uuid.UUID,
    active: bool,
) -> User:
    staff = StaffRepository(session, clinic.id)
    member = await staff.member(member_id)
    if member is None:
        raise NotFound("That person could not be found.")

    if member.id == actor.id:
        raise ValidationFailed({"status": "You cannot suspend your own account."})

    if not active:
        held = await staff.count_holding(OWNER)
        members_role = next(
            (r for u, r in await staff.listing() if u.id == member_id and r is not None), None
        )
        if held <= 1 and members_role is not None and members_role.slug == OWNER:
            raise LastAdministrator

    member.status = "active" if active else "suspended"
    await session.flush()
    return member
