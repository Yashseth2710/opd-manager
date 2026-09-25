"""The platform's screens: clinics, their plans, and the numbers across them."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ClinicStatus = Literal["pending", "active", "suspended"]


class PlanLimits(BaseModel):
    # None is no cap. Zero would mean a clinic could add nothing at all,
    # which is a suspension by another name.
    max_doctors: int | None = Field(default=None, ge=1, le=100_000)
    max_staff: int | None = Field(default=None, ge=1, le=100_000)
    max_patients: int | None = Field(default=None, ge=1, le=100_000_000)
    max_appointments_per_month: int | None = Field(default=None, ge=1, le=10_000_000)
    max_storage_mb: int | None = Field(default=None, ge=1, le=10_000_000)


class PlanOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    price_monthly: Decimal
    limits: PlanLimits
    clinics: int


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=64)
    description: str | None = Field(default=None, max_length=300)
    price_monthly: Decimal | None = Field(default=None, ge=0, le=1_000_000, decimal_places=2)
    limits: PlanLimits | None = None

    @field_validator("name", "description")
    @classmethod
    def _trimmed(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class Standing(BaseModel):
    """The plan a clinic is held to, and the one chosen for it when a trial
    has run out and the two differ."""

    plan_id: uuid.UUID
    plan_name: str
    chosen_name: str
    trial_ends_at: dt.datetime | None
    on_trial: bool
    trial_over: bool


class Owner(BaseModel):
    name: str
    email: str


class ClinicRow(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: ClinicStatus
    created_at: dt.datetime
    set_up: bool
    standing: Standing
    owner: Owner | None
    doctors: int
    staff: int
    patients: int
    appointments_this_month: int
    last_active_at: dt.datetime | None


class ClinicPage(BaseModel):
    items: list[ClinicRow]
    total: int
    page: int
    per_page: int
    pages: int
    statuses: dict[str, int]


class Measure(BaseModel):
    used: int
    limit: int | None


class PlatformEvent(BaseModel):
    id: uuid.UUID
    action: str
    actor_name: str
    changes: dict[str, Any] | None
    created_at: dt.datetime


class ClinicDetail(ClinicRow):
    phone: str | None
    email: str | None
    city: str | None
    timezone: str
    usage: dict[str, Measure]
    history: list[PlatformEvent]


class Suspension(BaseModel):
    reason: str = Field(min_length=3, max_length=300)

    @field_validator("reason")
    @classmethod
    def _said(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("Say why, in a few words.")
        return cleaned


class PlanChoice(BaseModel):
    plan_id: uuid.UUID


class Week(BaseModel):
    starts: dt.date
    clinics: int


class PlanShare(BaseModel):
    id: uuid.UUID
    name: str
    clinics: int


class Metrics(BaseModel):
    clinics: int
    statuses: dict[str, int]
    new_clinics_this_month: int
    accounts: int
    doctors: int
    patients: int
    appointments_this_month: int
    on_trial: int
    signups: list[Week]
    plans: list[PlanShare]
