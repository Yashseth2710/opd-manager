"""Clinic setup and the people who work there.

Every route that touches a clinic resolves the caller first and is gated on
a permission. The two open routes carry no session because whoever opens an
invitation link has no account yet; both are guarded by the token instead.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    Caller,
    DbSession,
    Trail,
    client_ip,
    current_caller,
    current_tenant,
    requires,
)
from app.api.v1.endpoints.auth import session_payload, set_session_cookies
from app.core.config import get_settings
from app.core.exceptions import NotFound, SessionExpired
from app.core.permissions import OWNER
from app.models import Organization, Role, User, UserRole
from app.models import notification as kinds
from app.repositories.staff import InvitationRepository, StaffRepository
from app.repositories.users import UserRepository
from app.schemas.auth import AcknowledgedOut, SessionOut
from app.schemas.clinic import (
    AcceptInvitation,
    ChangeRoleRequest,
    ClinicOut,
    ClinicSettingsOut,
    ClinicSettingsUpdate,
    ClinicUpdate,
    InvitationOut,
    InvitationPreview,
    InviteRequest,
    RoleOut,
    StaffMemberOut,
)
from app.services import auth as auth_service
from app.services import clinic as service
from app.services import events

router = APIRouter(tags=["clinic"])


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    found = await session.get(Organization, organization_id)
    if found is None:
        raise SessionExpired
    return found


async def _role_of(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    found = await session.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return found.scalars().first()


def _person(user: User) -> str:
    return f"{user.full_name} ({user.email})"


def _settings_out(clinic: Organization) -> ClinicSettingsOut:
    return ClinicSettingsOut.model_validate(clinic.effective_settings)


@router.get("/clinic")
async def read_clinic(
    session: DbSession,
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ClinicOut:
    """Readable by anyone signed in. A receptionist needs the clinic's name
    and opening details to do their job."""
    return ClinicOut.model_validate(await _clinic(session, organization_id))


@router.patch("/clinic")
async def update_clinic(
    session: DbSession,
    body: ClinicUpdate,
    trail: Trail,
    _: Caller = Depends(requires("settings:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ClinicOut:
    clinic = await _clinic(session, organization_id)
    fields = body.model_dump(exclude_unset=True)
    before = events.snapshot(ClinicOut.model_validate(clinic), fields)
    after = ClinicOut.model_validate(await service.update_clinic(session, clinic, body))
    moved = events.difference(before, events.snapshot(after, fields))
    if moved:
        await trail("clinic.details_changed", "clinic", after.id, after.name, moved)
    return after


@router.get("/clinic/settings")
async def read_settings(
    session: DbSession,
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ClinicSettingsOut:
    return _settings_out(await _clinic(session, organization_id))


@router.patch("/clinic/settings")
async def update_settings(
    session: DbSession,
    body: ClinicSettingsUpdate,
    trail: Trail,
    _: Caller = Depends(requires("settings:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ClinicSettingsOut:
    clinic = await _clinic(session, organization_id)
    fields = body.model_dump(exclude_unset=True)
    before = events.snapshot(_settings_out(clinic), fields)
    after = _settings_out(await service.update_settings(session, clinic, body))
    moved = events.difference(before, events.snapshot(after, fields))
    if moved:
        await trail("clinic.settings_changed", "clinic", clinic.id, clinic.name, moved)
    return after


@router.post("/clinic/complete-setup")
async def complete_setup(
    session: DbSession,
    trail: Trail,
    _: Caller = Depends(requires("settings:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ClinicOut:
    """Opens the clinic for business. Refuses while the details it cannot
    operate without are still missing."""
    clinic = await _clinic(session, organization_id)
    opened = ClinicOut.model_validate(await service.finish_setup(session, clinic))
    await trail("clinic.opened", "clinic", opened.id, opened.name)
    return opened


@router.get("/clinic/roles")
async def list_roles(
    session: DbSession,
    _: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> list[RoleOut]:
    roles = await StaffRepository(session, organization_id).roles()
    return [RoleOut.model_validate(role) for role in roles]


@router.get("/staff")
async def list_staff(
    session: DbSession,
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> list[StaffMemberOut]:
    listing = await StaffRepository(session, organization_id).listing()
    return [
        StaffMemberOut(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            phone=user.phone,
            status=user.status,
            role=RoleOut.model_validate(role) if role else None,
            email_verified=user.is_verified,
            last_login_at=user.last_login_at,
            is_you=user.id == caller.user_id,
        )
        for user, role in listing
    ]


@router.patch("/staff/{member_id}/role")
async def change_role(
    session: DbSession,
    member_id: uuid.UUID,
    body: ChangeRoleRequest,
    trail: Trail,
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AcknowledgedOut:
    actor = await UserRepository(session).get(caller.user_id)
    if actor is None:
        raise SessionExpired
    clinic = await _clinic(session, organization_id)
    was = await _role_of(session, member_id)
    member = await service.change_role(
        session, clinic=clinic, actor=actor, member_id=member_id, role_slug=body.role_slug
    )
    now = await _role_of(session, member_id)
    if was != now:
        await trail(
            "staff.role_changed", "staff", member.id, _person(member), {"role": [was, now]}
        )
        await trail.tell(
            [member.id],
            events.Notice(
                kind=kinds.ROLE_CHANGED,
                title=f"{actor.full_name} made you {(now or 'a member of staff').lower()}",
                body=(
                    f"You were {(was or 'without a role').lower()}. "
                    "Sign out and back in to see everything the new role opens."
                ),
                link=None,
            ),
        )
    return AcknowledgedOut()


@router.post("/staff/{member_id}/suspend")
async def suspend_member(
    session: DbSession,
    member_id: uuid.UUID,
    trail: Trail,
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AcknowledgedOut:
    actor = await UserRepository(session).get(caller.user_id)
    if actor is None:
        raise SessionExpired
    clinic = await _clinic(session, organization_id)
    member = await service.set_member_status(
        session, clinic=clinic, actor=actor, member_id=member_id, active=False
    )
    await trail("staff.suspended", "staff", member.id, _person(member))
    return AcknowledgedOut()


@router.post("/staff/{member_id}/restore")
async def restore_member(
    session: DbSession,
    member_id: uuid.UUID,
    trail: Trail,
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AcknowledgedOut:
    actor = await UserRepository(session).get(caller.user_id)
    if actor is None:
        raise SessionExpired
    clinic = await _clinic(session, organization_id)
    member = await service.set_member_status(
        session, clinic=clinic, actor=actor, member_id=member_id, active=True
    )
    await trail("staff.restored", "staff", member.id, _person(member))
    return AcknowledgedOut()


@router.get("/staff/invitations")
async def list_invitations(
    session: DbSession,
    _: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> list[InvitationOut]:
    pending = await InvitationRepository(session, organization_id).pending()
    return [
        InvitationOut(
            id=invitation.id,
            email=invitation.email,
            role=RoleOut.model_validate(role),
            invited_by_name=invitation.invited_by_name,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
        )
        for invitation, role in pending
    ]


@router.post("/staff/invitations", status_code=201)
async def send_invitation(
    session: DbSession,
    body: InviteRequest,
    trail: Trail,
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AcknowledgedOut:
    inviter = await UserRepository(session).get(caller.user_id)
    if inviter is None:
        raise SessionExpired
    clinic = await _clinic(session, organization_id)

    await service.invite(
        session,
        clinic=clinic,
        inviter=inviter,
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        role_slug=body.role_slug,
    )
    named = f"{body.first_name} {body.last_name or ''}".strip()
    await trail(
        "staff.invited",
        "invitation",
        None,
        f"{named} ({body.email})",
        {"role": body.role_slug},
    )
    # Reports whether a provider exists, not whether this one was delivered,
    # so the answer is the same for every address.
    return AcknowledgedOut(email_configured=get_settings().email_configured)


@router.delete("/staff/invitations/{invitation_id}")
async def revoke_invitation(
    session: DbSession,
    invitation_id: uuid.UUID,
    trail: Trail,
    _: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AcknowledgedOut:
    clinic = await _clinic(session, organization_id)
    invitation = await InvitationRepository(session, organization_id).get(invitation_id)
    await service.revoke(session, clinic, invitation_id)
    if invitation is not None:
        await trail("staff.invitation_withdrawn", "invitation", None, invitation.email)
    return AcknowledgedOut()


@router.get("/invitations/{token}")
async def preview_invitation(
    session: DbSession,
    token: str,
) -> InvitationPreview:
    """Open, because whoever follows the link has no account yet.

    It shows the clinic and the role and nothing else. Holding the link does
    not prove they are the intended recipient, so it must not become a way to
    read anything about the clinic.
    """
    invitation, clinic, role_name = await service.preview(session, token)
    return InvitationPreview(
        clinic_name=clinic.name,
        role_name=role_name,
        email=invitation.email,
        first_name=invitation.first_name,
    )


@router.post("/invitations/accept")
async def accept_invitation(
    session: DbSession,
    body: AcceptInvitation,
    request: Request,
    response: Response,
) -> SessionOut:
    """Turns an invitation into an account, and signs them in.

    The clinic and role come from the invitation, never from the request, so
    a link cannot be redeemed into a role nobody granted.

    They are signed in straight away for the same reason registering signs
    somebody in: they have just proved they read mail at that address and
    chosen a password. Sending them to a sign-in form to type both again
    would be asking them to prove it twice.
    """
    user = await service.accept(
        session, token=body.token, password=body.password, client_ip=client_ip(request)
    )
    organization_id = user.organization_id
    if organization_id is None:
        raise SessionExpired
    role = await _role_of(session, user.id)
    await events.record(
        session,
        organization_id=organization_id,
        actor=events.Actor(
            id=user.id,
            name=user.full_name,
            ip=client_ip(request),
            agent=request.headers.get("user-agent"),
        ),
        action="staff.joined",
        resource_type="staff",
        resource_id=user.id,
        label=_person(user),
        changes={"role": role},
    )
    await events.tell(
        session,
        organization_id=organization_id,
        users=await events.in_role(session, organization_id, OWNER),
        notice=events.Notice(
            kind=kinds.STAFF_JOINED,
            title=f"{user.full_name} joined as {(role or 'staff').lower()}",
            body=f"They accepted the invitation sent to {user.email}.",
            link="/staff",
        ),
        besides=user.id,
    )
    signed_in = await auth_service.start_session(session, user)
    set_session_cookies(response, signed_in)
    return session_payload(signed_in)


@router.get("/clinic/needs-setup")
async def needs_setup(
    session: DbSession,
    _: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> dict[str, bool]:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    return {"needs_setup": not clinic.is_set_up}
