"""Request and response shapes for clinic setup and staff."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Money crosses the wire as a string. A JSON number is a double, and a double
# cannot hold 0.1 + 0.2, which is not a property to give a clinic's fees.
Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2, ge=0)]


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class Address(_Trimmed):
    line1: str = Field(default="", max_length=160)
    line2: str = Field(default="", max_length=160)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=80)
    postal_code: str = Field(default="", max_length=16)
    country: str = Field(default="India", max_length=80)


class ClinicUpdate(_Trimmed):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    website: str | None = Field(default=None, max_length=255)
    timezone: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    address: Address | None = None

    @field_validator("currency")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class ClinicSettingsUpdate(_Trimmed):
    consultation_duration_minutes: int | None = Field(default=None, ge=5, le=240)
    consultation_fee: Money | None = None
    follow_up_fee: Money | None = None
    follow_up_window_days: int | None = Field(default=None, ge=0, le=365)
    tax_percent: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)] | None = None
    invoice_prefix: str | None = Field(default=None, min_length=1, max_length=8)
    token_prefix: str | None = Field(default=None, min_length=1, max_length=4)


class ClinicSettingsOut(BaseModel):
    consultation_duration_minutes: int
    consultation_fee: str
    follow_up_fee: str
    follow_up_window_days: int
    tax_percent: str
    invoice_prefix: str
    token_prefix: str


class ClinicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    phone: str | None
    email: str | None
    website: str | None
    timezone: str
    currency: str
    status: str
    address: dict[str, Any] | None
    onboarding_completed_at: dt.datetime | None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str


class StaffMemberOut(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: str | None
    status: str
    role: RoleOut | None
    email_verified: bool
    last_login_at: dt.datetime | None
    is_you: bool


class InviteRequest(_Trimmed):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    role_slug: str = Field(min_length=1, max_length=48)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: RoleOut
    invited_by_name: str
    expires_at: dt.datetime
    created_at: dt.datetime


class InvitationPreview(BaseModel):
    """What someone opening an invitation link is shown before they accept.

    Only the clinic and the role. Nothing about who else works there, because
    whoever holds this link has not proved they are the intended recipient.
    """

    clinic_name: str
    role_name: str
    email: str
    first_name: str


class AcceptInvitation(_Trimmed):
    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=128)


class ChangeRoleRequest(_Trimmed):
    role_slug: str = Field(min_length=1, max_length=48)
