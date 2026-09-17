"""Clinic setup and the people who work there.

Every route that touches a clinic resolves the caller first and is gated on
a permission. The two open routes carry no session because whoever opens an
invitation link has no account yet; both are guarded by the token instead.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, client_ip, current_caller, current_tenant, db_session, requires
from app.core.config import get_settings
from app.core.exceptions import NotFound, SessionExpired
from app.models import Organization
from app.repositories.staff import InvitationRepository, StaffRepository
from app.repositories.users import UserRepository
from app.schemas.auth import AcknowledgedOut
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
from app.services import clinic as service

router = APIRouter(tags=["clinic"])


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    found = await session.get(Organization, organization_id)
    if found is None:
        raise SessionExpired
    return found


def _settings_out(clinic: Organization) -> ClinicSettingsOut:
    return ClinicSettingsOut.model_validate(clinic.effective_settings)


@router.get("/clinic")
async def read_clinic(
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> ClinicOut:
    """Readable by anyone signed in. A receptionist needs the clinic's name
    and opening details to do their job."""
    return ClinicOut.model_validate(await _clinic(session, organization_id))


@router.patch("/clinic")
async def update_clinic(
    body: ClinicUpdate,
    _: Caller = Depends(requires("settings:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> ClinicOut:
    clinic = await _clinic(session, organization_id)
    return ClinicOut.model_validate(await service.update_clinic(session, clinic, body))


@router.get("/clinic/settings")
async def read_settings(
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> ClinicSettingsOut:
    return _settings_out(await _clinic(session, organization_id))


@router.patch("/clinic/settings")
async def update_settings(
    body: ClinicSettingsUpdate,
    _: Caller = Depends(requires("settings:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> ClinicSettingsOut:
    clinic = await _clinic(session, organization_id)
    return _settings_out(await service.update_settings(session, clinic, body))


@router.post("/clinic/complete-setup")
async def complete_setup(
    _: Caller = Depends(requires("settings:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> ClinicOut:
    """Opens the clinic for business. Refuses while the details it cannot
    operate without are still missing."""
    clinic = await _clinic(session, organization_id)
    return ClinicOut.model_validate(await service.finish_setup(session, clinic))


@router.get("/clinic/roles")
async def list_roles(
    _: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> list[RoleOut]:
    roles = await StaffRepository(session, organization_id).roles()
    return [RoleOut.model_validate(role) for role in roles]


@router.get("/staff")
async def list_staff(
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
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
    member_id: uuid.UUID,
    body: ChangeRoleRequest,
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> AcknowledgedOut:
    actor = await UserRepository(session).get(caller.user_id)
    if actor is None:
        raise SessionExpired
    clinic = await _clinic(session, organization_id)
    await service.change_role(
        session, clinic=clinic, actor=actor, member_id=member_id, role_slug=body.role_slug
    )
    return AcknowledgedOut()


@router.post("/staff/{member_id}/suspend")
async def suspend_member(
    member_id: uuid.UUID,
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> AcknowledgedOut:
    actor = await UserRepository(session).get(caller.user_id)
    if actor is None:
        raise SessionExpired
    clinic = await _clinic(session, organization_id)
    await service.set_member_status(
        session, clinic=clinic, actor=actor, member_id=member_id, active=False
    )
    return AcknowledgedOut()


@router.post("/staff/{member_id}/restore")
async def restore_member(
    member_id: uuid.UUID,
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> AcknowledgedOut:
    actor = await UserRepository(session).get(caller.user_id)
    if actor is None:
        raise SessionExpired
    clinic = await _clinic(session, organization_id)
    await service.set_member_status(
        session, clinic=clinic, actor=actor, member_id=member_id, active=True
    )
    return AcknowledgedOut()


@router.get("/staff/invitations")
async def list_invitations(
    _: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
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
    body: InviteRequest,
    caller: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
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
    # Reports whether a provider exists, not whether this one was delivered,
    # so the answer is the same for every address.
    return AcknowledgedOut(email_configured=get_settings().email_configured)


@router.delete("/staff/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: uuid.UUID,
    _: Caller = Depends(requires("staff:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> AcknowledgedOut:
    clinic = await _clinic(session, organization_id)
    await service.revoke(session, clinic, invitation_id)
    return AcknowledgedOut()


@router.get("/invitations/{token}")
async def preview_invitation(
    token: str,
    session: AsyncSession = Depends(db_session),
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
    body: AcceptInvitation,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(db_session),
) -> AcknowledgedOut:
    """Turns an invitation into an account.

    The clinic and role come from the invitation, never from the request, so
    a link cannot be redeemed into a role nobody granted.
    """
    await service.accept(
        session, token=body.token, password=body.password, client_ip=client_ip(request)
    )
    return AcknowledgedOut()


@router.get("/clinic/needs-setup")
async def needs_setup(
    _: Caller = Depends(current_caller),
    organization_id: uuid.UUID = Depends(current_tenant),
    session: AsyncSession = Depends(db_session),
) -> dict[str, bool]:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    return {"needs_setup": not clinic.is_set_up}
