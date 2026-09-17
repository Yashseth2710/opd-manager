"""Request and response shapes for the sign-in and recovery endpoints."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class RegisterRequest(_Trimmed):
    clinic_name: str = Field(min_length=2, max_length=160)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    timezone: str = Field(default="Asia/Kolkata", max_length=64)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


class LoginRequest(_Trimmed):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    # Only needed when the address has an account at more than one clinic.
    organization_slug: str | None = Field(default=None, max_length=80)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


class ForgotPasswordRequest(_Trimmed):
    email: EmailStr


class ResetPasswordRequest(_Trimmed):
    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=128)


class VerifyEmailRequest(_Trimmed):
    token: str = Field(min_length=1, max_length=256)


class ResendVerificationRequest(_Trimmed):
    email: EmailStr


class ClinicChoice(BaseModel):
    slug: str
    name: str


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    timezone: str
    currency: str
    status: str
    onboarding_completed_at: dt.datetime | None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    phone: str | None
    status: str
    email_verified_at: dt.datetime | None


class SessionOut(BaseModel):
    """What the browser gets after a successful sign-in.

    The tokens are not in here. They are set as httpOnly cookies, so script
    on the page cannot read them and an injection cannot carry them off.
    """

    user: UserOut
    organization: OrganizationOut | None
    role: str
    permissions: list[str]


class RegisterOut(BaseModel):
    session: SessionOut | None
    verification_required: bool
    email_delivered: bool


class AcknowledgedOut(BaseModel):
    """Deliberately says nothing about whether an account exists.

    `email_configured` reports whether a provider is set up at all, which is
    the same answer for every address. Reporting whether a message actually
    went out would be true only for addresses that have an account, which is
    precisely what the identical acknowledgement exists to hide.
    """

    acknowledged: bool = True
    email_configured: bool = False
