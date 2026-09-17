"""Request and response shapes for doctors, their week and their leave."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.patient import normalised_phone

# Spelled out rather than built from the model's tuples so the generated API
# schema lists the values. A test holds the two in step.
Title = Literal["Dr", "Prof", "Mr", "Ms", "Mrs"]
DoctorStatus = Literal["active", "inactive"]

Money = Annotated[Decimal, Field(ge=0, le=Decimal("9999999.99"), decimal_places=2)]

# A slot shorter than five minutes is a typo, and a working block longer than
# a day cannot be described by a start and end time at all.
MIN_SLOT_MINUTES = 5
MAX_SLOT_MINUTES = 240


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


def tidy_languages(value: list[str] | None) -> list[str] | None:
    """Trimmed, de-duplicated regardless of case, and empty means none.

    The form sends one text box split on commas, so "Hindi, hindi, " is the
    ordinary case rather than an odd one.
    """
    if value is None:
        return None
    kept: list[str] = []
    seen: set[str] = set()
    for language in value:
        trimmed = language.strip()[:40]
        if trimmed and trimmed.casefold() not in seen:
            seen.add(trimmed.casefold())
            kept.append(trimmed)
    return kept or None


class DoctorWrite(_Trimmed):
    """The fields a person fills in, on both adding and editing."""

    title: Title = "Dr"
    first_name: str = Field(min_length=1, max_length=80)
    # Nullable for the same reason a patient's is: one name is a whole name.
    last_name: str | None = Field(default="", max_length=80)

    speciality: str | None = Field(default=None, max_length=80)
    qualifications: str | None = Field(default=None, max_length=160)
    registration_number: str | None = Field(default=None, max_length=48)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)

    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    room: str | None = Field(default=None, max_length=32)

    languages: list[str] | None = Field(default=None, max_length=12)
    bio: str | None = Field(default=None, max_length=2000)

    # Left out entirely to follow the clinic's figure. Sent as null to go
    # back to following it after having been set.
    consultation_fee: Money | None = None
    follow_up_fee: Money | None = None
    slot_duration_minutes: int | None = Field(
        default=None, ge=MIN_SLOT_MINUTES, le=MAX_SLOT_MINUTES
    )

    # The staff account this profile belongs to, where there is one.
    user_id: uuid.UUID | None = None

    @field_validator("last_name")
    @classmethod
    def _blank_rather_than_missing(cls, value: str | None) -> str:
        return value or ""

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return normalised_phone(value)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str | None) -> str | None:
        return value.lower() if value else None

    @field_validator("languages")
    @classmethod
    def _tidy_languages(cls, value: list[str] | None) -> list[str] | None:
        return tidy_languages(value)


class DoctorCreate(DoctorWrite):
    pass


class DoctorUpdate(_Trimmed):
    """Every field optional, so editing a room number cannot wipe a bio."""

    title: Title | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)

    speciality: str | None = Field(default=None, max_length=80)
    qualifications: str | None = Field(default=None, max_length=160)
    registration_number: str | None = Field(default=None, max_length=48)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)

    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    room: str | None = Field(default=None, max_length=32)

    languages: list[str] | None = Field(default=None, max_length=12)
    bio: str | None = Field(default=None, max_length=2000)

    consultation_fee: Money | None = None
    follow_up_fee: Money | None = None
    slot_duration_minutes: int | None = Field(
        default=None, ge=MIN_SLOT_MINUTES, le=MAX_SLOT_MINUTES
    )

    user_id: uuid.UUID | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return normalised_phone(value)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str | None) -> str | None:
        return value.lower() if value else None

    @field_validator("languages")
    @classmethod
    def _tidy_languages(cls, value: list[str] | None) -> list[str] | None:
        return tidy_languages(value)


class ScheduleBlock(_Trimmed):
    day_of_week: int = Field(ge=0, le=6)
    start_time: dt.time
    end_time: dt.time
    break_start: dt.time | None = None
    break_end: dt.time | None = None
    slot_duration_minutes: int | None = Field(
        default=None, ge=MIN_SLOT_MINUTES, le=MAX_SLOT_MINUTES
    )


class ScheduleWrite(BaseModel):
    """The whole week, every time.

    A schedule is replaced rather than patched block by block. Anything else
    means two receptionists editing Tuesday can leave a doctor sitting in two
    rooms at once, and replacing the set inside one transaction makes the
    overlap check below the truth rather than a guess.
    """

    blocks: list[ScheduleBlock] = Field(default_factory=list, max_length=60)


class ScheduleBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    day_of_week: int
    start_time: dt.time
    end_time: dt.time
    break_start: dt.time | None
    break_end: dt.time | None
    slot_duration_minutes: int | None


class LeaveWrite(_Trimmed):
    starts_on: dt.date
    ends_on: dt.date | None = None
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    reason: str | None = Field(default=None, max_length=200)


class LeaveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    starts_on: dt.date
    ends_on: dt.date
    start_time: dt.time | None
    end_time: dt.time | None
    reason: str | None
    created_at: dt.datetime


class DoctorSummary(BaseModel):
    id: uuid.UUID
    display_name: str
    full_name: str
    title: str
    speciality: str | None
    qualifications: str | None
    room: str | None
    status: str
    # The figure that actually applies, the doctor's own or the clinic's.
    consultation_fee: str
    # True when that figure came from the clinic rather than this profile.
    fee_from_clinic: bool
    slot_duration_minutes: int
    # Blocks in the week, so a list can say who has no hours set yet.
    working_days: int
    has_account: bool
    created_at: dt.datetime


class DoctorOut(DoctorSummary):
    first_name: str
    last_name: str
    registration_number: str | None
    years_of_experience: int | None
    phone: str | None
    email: str | None
    languages: list[str] | None
    bio: str | None
    follow_up_fee: str
    follow_up_fee_from_clinic: bool
    own_consultation_fee: str | None
    own_follow_up_fee: str | None
    own_slot_duration_minutes: int | None
    user_id: uuid.UUID | None
    account_name: str | None
    deactivated_at: dt.datetime | None
    schedule: list[ScheduleBlockOut]
    leaves: list[LeaveOut]


class DoctorPage(BaseModel):
    items: list[DoctorSummary]
    total: int
    page: int
    per_page: int
    pages: int


class Slot(BaseModel):
    start_time: dt.time
    end_time: dt.time


class Availability(BaseModel):
    """What a doctor's day looks like, worked out rather than stored.

    Materialising slots would mean regenerating them every time a schedule
    changed, and a stale slot table is a classic way to double-book somebody.
    """

    date: dt.date
    day_of_week: int
    day_name: str
    working: bool
    # Said in the clinic's words, for the screen that shows nothing: "Not
    # working on Sundays", "On leave until 4 October".
    reason: str | None
    slot_duration_minutes: int
    slots: list[Slot]


class Removed(BaseModel):
    removed: bool = True
