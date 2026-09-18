"""Request and response shapes for prescriptions and the medicine list."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.appointment import DoctorRef, PatientRef

Timing = Literal[
    "before_food", "after_food", "with_food", "empty_stomach", "bedtime", "as_needed"
]
PrescriptionStatus = Literal["draft", "issued", "replaced"]

MAX_LINES = 30


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class MedicineLine(_Trimmed):
    """One medicine as the doctor has written it so far. A dose is needed by
    the time the prescription is issued, not while it is being typed."""

    medicine_name: str = Field(min_length=1, max_length=200)
    presentation: str | None = Field(default=None, max_length=200)
    dose: str | None = Field(default=None, max_length=40)
    timing: Timing | None = None
    duration_days: int | None = Field(default=None, ge=1, le=365)
    instructions: str | None = Field(default=None, max_length=200)


class Correction(_Trimmed):
    medicines: list[MedicineLine] = Field(min_length=1, max_length=MAX_LINES)
    instructions: str | None = Field(default=None, max_length=2000)
    reason: str = Field(min_length=1, max_length=200)


class LineOut(BaseModel):
    medicine_name: str
    presentation: str | None
    dose: str | None
    timing: Timing | None
    duration_days: int | None
    instructions: str | None


class PrescriptionRef(BaseModel):
    id: uuid.UUID
    number: str | None


class PrescriptionOut(BaseModel):
    id: uuid.UUID
    number: str | None
    status: PrescriptionStatus
    issued_at: dt.datetime | None
    follow_up_date: dt.date | None
    instructions: str | None
    items: list[LineOut]
    replaces: PrescriptionRef | None
    replaced_by: PrescriptionRef | None
    correction_reason: str | None


class Prescriber(BaseModel):
    id: uuid.UUID
    display_name: str
    speciality: str | None
    qualifications: str | None
    registration_number: str | None


class ClinicHeader(BaseModel):
    name: str
    address: list[str]
    phone: str | None
    email: str | None


class PrescriptionDetail(PrescriptionOut):
    patient: PatientRef
    doctor: Prescriber
    clinic: ClinicHeader
    consultation_id: uuid.UUID
    visit_date: dt.date
    can_correct: bool


class PrescriptionSummary(BaseModel):
    id: uuid.UUID
    number: str | None
    status: PrescriptionStatus
    issued_at: dt.datetime | None
    patient: PatientRef
    doctor: DoctorRef
    medicines: list[str]


class PrescriptionPage(BaseModel):
    items: list[PrescriptionSummary]
    total: int


class MedicineSuggestion(BaseModel):
    name: str
    presentation: str | None
    # "clinic" when this clinic has prescribed it before, "list" when it
    # comes from the published list only.
    source: Literal["clinic", "list"]
    times_prescribed: int
