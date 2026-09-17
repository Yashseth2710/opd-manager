"""Request and response shapes for patient records."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Spelled out rather than built from the model's tuples so the generated
# API schema lists the values. A test holds the two in step.
Gender = Literal["female", "male", "other"]
BloodGroup = Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
Severity = Literal["mild", "moderate", "severe"]

_DIGITS = re.compile(r"\D")


def normalised_phone(value: str | None) -> str | None:
    """Kept as the digits plus an optional country prefix.

    Clinics type numbers with spaces, dashes and brackets, and two records
    that differ only in punctuation are two records as far as duplicate
    detection is concerned.
    """
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    plus = trimmed.startswith("+")
    digits = _DIGITS.sub("", trimmed)
    if not digits:
        return None
    return f"+{digits}" if plus else digits


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class PatientAddress(_Trimmed):
    line1: str = Field(default="", max_length=160)
    line2: str = Field(default="", max_length=160)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=80)
    postal_code: str = Field(default="", max_length=16)
    country: str = Field(default="India", max_length=80)


class EmergencyContact(_Trimmed):
    name: str = Field(default="", max_length=120)
    relationship: str = Field(default="", max_length=60)
    phone: str = Field(default="", max_length=32)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return normalised_phone(value) or ""


class PatientWrite(_Trimmed):
    """The fields a person fills in, on both registration and editing."""

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(default="", max_length=80)
    preferred_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=32)
    alternate_phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    date_of_birth: dt.date | None = None
    gender: Gender | None = None
    blood_group: BloodGroup | None = None
    address: PatientAddress | None = None
    emergency_contact: EmergencyContact | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("phone", "alternate_phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return normalised_phone(value)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str | None) -> str | None:
        return value.lower() if value else None


class PatientCreate(PatientWrite):
    # Set once the person has seen the possible duplicates and said this is
    # somebody else. Never defaulted on: a silent duplicate is a split
    # history, and a split history is the one thing this record must not do.
    confirm_duplicate: bool = False


class PatientUpdate(_Trimmed):
    """Every field optional, because a PATCH that has to resend the whole
    record turns an edit of one phone number into a chance to wipe the rest."""

    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    preferred_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=32)
    alternate_phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    date_of_birth: dt.date | None = None
    gender: Gender | None = None
    blood_group: BloodGroup | None = None
    address: PatientAddress | None = None
    emergency_contact: EmergencyContact | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("phone", "alternate_phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return normalised_phone(value)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str | None) -> str | None:
        return value.lower() if value else None


class DuplicateCheck(_Trimmed):
    first_name: str = Field(default="", max_length=80)
    last_name: str = Field(default="", max_length=80)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    date_of_birth: dt.date | None = None
    # Excluded from its own results when an existing record is being edited.
    exclude_id: uuid.UUID | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return normalised_phone(value)


class AllergyWrite(_Trimmed):
    substance: str = Field(min_length=1, max_length=120)
    reaction: str | None = Field(default=None, max_length=200)
    severity: Severity = "moderate"


class AllergyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    substance: str
    reaction: str | None
    severity: str
    created_at: dt.datetime


class PatientSummary(BaseModel):
    id: uuid.UUID
    patient_number: str
    full_name: str
    preferred_name: str | None
    phone: str | None
    date_of_birth: dt.date | None
    age: str | None
    gender: str | None
    blood_group: str | None
    status: str
    allergy_count: int
    created_at: dt.datetime


class PatientOut(PatientSummary):
    first_name: str
    last_name: str
    alternate_phone: str | None
    email: str | None
    address: dict[str, Any] | None
    emergency_contact: dict[str, Any] | None
    notes: str | None
    archived_at: dt.datetime | None
    registered_by_name: str | None
    allergies: list[AllergyOut]


class DuplicateCandidate(PatientSummary):
    # Why this record surfaced, so the person deciding can see it at a glance
    # rather than comparing two forms field by field.
    reason: str


class PatientPage(BaseModel):
    items: list[PatientSummary]
    total: int
    page: int
    per_page: int
    pages: int


class Removed(BaseModel):
    removed: bool = True
