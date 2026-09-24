"""Sign-in, registration and account recovery.

Tokens travel as httpOnly cookies rather than in the response body, so script
running on the page cannot read them and an injected script cannot carry a
session away.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    SESSION_HINT_COOKIE,
    Caller,
    DbSession,
    client_ip,
    current_caller,
)
from app.core.config import get_settings
from app.core.exceptions import SessionExpired
from app.core.security import mint_access_token
from app.repositories.users import OrganizationRepository, UserRepository
from app.schemas.auth import (
    AcknowledgedOut,
    ForgotPasswordRequest,
    LoginRequest,
    OrganizationOut,
    RegisterOut,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SessionOut,
    UserOut,
    VerifyEmailRequest,
)
from app.services import auth, sessions

router = APIRouter(prefix="/auth", tags=["auth"])


def _secure_cookies() -> bool:
    # Secure cookies are not sent over plain http, which would break local
    # development on localhost.
    return get_settings().environment != "development"


def set_session_cookies(response: Response, signed_in: auth.SignedIn) -> None:
    settings = get_settings()
    secure = _secure_cookies()

    response.set_cookie(
        ACCESS_COOKIE,
        signed_in.access_token,
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        signed_in.refresh_token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        # Only sent to the endpoints that need it, so it is not attached to
        # every ordinary request.
        path="/api/v1/auth",
    )
    response.set_cookie(
        SESSION_HINT_COOKIE,
        "1",
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.delete_cookie(SESSION_HINT_COOKIE, path="/")


def session_payload(signed_in: auth.SignedIn) -> SessionOut:
    return SessionOut(
        user=UserOut.model_validate(signed_in.user),
        organization=(
            OrganizationOut.model_validate(signed_in.organization)
            if signed_in.organization
            else None
        ),
        role=signed_in.role,
        permissions=signed_in.permissions,
    )


@router.post("/register", status_code=201)
async def register(
    session: DbSession,
    body: RegisterRequest,
    response: Response,
    request: Request,
) -> RegisterOut:
    result = await auth.register(
        session,
        clinic_name=body.clinic_name,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password=body.password,
        phone=body.phone,
        timezone=body.timezone,
        client_ip=client_ip(request),
    )

    if result.session is None:
        return RegisterOut(
            session=None,
            verification_required=result.verification_required,
            email_delivered=result.email_delivered,
        )

    set_session_cookies(response, result.session)
    return RegisterOut(
        session=session_payload(result.session),
        verification_required=False,
        email_delivered=result.email_delivered,
    )


@router.post("/login")
async def login(
    session: DbSession,
    body: LoginRequest,
    response: Response,
    request: Request,
) -> SessionOut:
    signed_in = await auth.sign_in(
        session,
        email=body.email,
        password=body.password,
        organization_slug=body.organization_slug,
        client_ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookies(response, signed_in)
    return session_payload(signed_in)


@router.post("/refresh")
async def refresh(
    session: DbSession,
    request: Request,
    response: Response,
) -> SessionOut:
    """Exchanges a refresh token for a new pair.

    The old token stops working the moment it is used. Presenting one twice
    is treated as a replay and ends every session in that family.
    """
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise SessionExpired

    try:
        rotated = await sessions.rotate(token)
    except sessions.ReplayDetected:
        _clear_session_cookies(response)
        raise SessionExpired("That session was ended for safety. Sign in again.") from None

    if rotated is None:
        _clear_session_cookies(response)
        raise SessionExpired

    refresh_token, opened = rotated

    user = await UserRepository(session).get(opened.user_id)
    if user is None or user.status != "active":
        _clear_session_cookies(response)
        raise SessionExpired

    role, permissions = await UserRepository(session).permissions_for(user)
    organization = None
    if user.organization_id is not None:
        organization = await OrganizationRepository(session).get(user.organization_id)

    signed_in = auth.SignedIn(
        user=user,
        organization=organization,
        role=role,
        permissions=permissions,
        access_token=mint_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            role=role,
            permissions=permissions,
            session_id=opened.session_id,
        ),
        refresh_token=refresh_token,
    )
    set_session_cookies(response, signed_in)
    return session_payload(signed_in)


@router.post("/logout")
async def logout(request: Request, response: Response) -> AcknowledgedOut:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await sessions.close_session(token)
    _clear_session_cookies(response)
    return AcknowledgedOut()


@router.get("/me")
async def me(
    session: DbSession,
    caller: Caller = Depends(current_caller),
) -> SessionOut:
    user = await UserRepository(session).get(caller.user_id)
    if user is None or user.status != "active":
        raise SessionExpired

    organization = None
    if user.organization_id is not None:
        organization = await OrganizationRepository(session).get(user.organization_id)

    return SessionOut(
        user=UserOut.model_validate(user),
        organization=(OrganizationOut.model_validate(organization) if organization else None),
        role=caller.role,
        permissions=sorted(caller.permissions),
    )


@router.post("/forgot-password")
async def forgot_password(
    session: DbSession,
    body: ForgotPasswordRequest,
) -> AcknowledgedOut:
    """Answers the same way whether or not the address has an account."""
    await auth.request_password_reset(session, email=body.email)
    return AcknowledgedOut(email_configured=get_settings().email_configured)


@router.post("/reset-password")
async def reset_password(
    session: DbSession,
    body: ResetPasswordRequest,
    response: Response,
) -> AcknowledgedOut:
    await auth.complete_password_reset(session, token=body.token, password=body.password)
    # Every session on the account has just been revoked, including this one.
    _clear_session_cookies(response)
    return AcknowledgedOut()


@router.post("/verify-email")
async def verify_email(
    session: DbSession,
    body: VerifyEmailRequest,
) -> AcknowledgedOut:
    await auth.verify_email(session, token=body.token)
    return AcknowledgedOut()


@router.post("/resend-verification")
async def resend_verification(
    session: DbSession,
    body: ResendVerificationRequest,
) -> AcknowledgedOut:
    await auth.resend_verification(session, email=body.email)
    return AcknowledgedOut(email_configured=get_settings().email_configured)
