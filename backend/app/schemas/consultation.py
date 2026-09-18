"""Request and response shapes for consultation notes."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.appointment import DoctorRef, PatientRef
from app.schemas.prescription import MAX_LINES, MedicineLine, PrescriptionOut
from app.schemas.queue import BookedFor

ConsultationStatus = Literal["draft", "completed"]

# Long enough for a thorough history, short enough that a pasted document
# is refused rather than stored as a note.
LONG_TEXT = 10_000


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class ConsultationOpen(_Trimmed):
    queue_entry_id: uuid.UUID


class DiagnosisIn(_Trimmed):
    label: str = Field(min_length=1, max_length=200)
    is_primary: bool = False


class ConsultationWrite(_Trimmed):
    """A save while the doctor writes. Only the fields sent change, so each
    section can be saved on its own; `version` is the copy it was written
    against."""

    version: int = Field(ge=1)
    chief_complaint: str | None = Field(default=None, max_length=500)
    history: str | None = Field(default=None, max_length=LONG_TEXT)
    examination: str | None = Field(default=None, max_length=LONG_TEXT)
    advice: str | None = Field(default=None, max_length=LONG_TEXT)
    diagnoses: list[DiagnosisIn] | None = Field(default=None, max_length=20)
    follow_up_date: dt.date | None = None
    # The prescription being written with these notes, as the whole list.
    medicines: list[MedicineLine] | None = Field(default=None, max_length=MAX_LINES)
    prescription_instructions: str | None = Field(default=None, max_length=2000)


class ConsultationFinish(_Trimmed):
    version: int = Field(ge=1)


class AddendumWrite(_Trimmed):
    body: str = Field(min_length=1, max_length=5000)


class DiagnosisOut(BaseModel):
    label: str
    is_primary: bool


class AddendumOut(BaseModel):
    id: uuid.UUID
    body: str
    written_by: str | None
    created_at: dt.datetime


class ConsultationSummary(BaseModel):
    id: uuid.UUID
    status: ConsultationStatus
    patient: PatientRef
    doctor: DoctorRef
    # The clinic's date the patient was seen on.
    visit_date: dt.date
    started_at: dt.datetime
    completed_at: dt.datetime | None
    token: int | None
    chief_complaint: str | None
    primary_diagnosis: str | None
    diagnosis_count: int
    follow_up_date: dt.date | None
    addendum_count: int


class ConsultationDetail(ConsultationSummary):
    version: int
    queue_entry_id: uuid.UUID | None
    appointment: BookedFor | None
    history: str | None
    examination: str | None
    advice: str | None
    diagnoses: list[DiagnosisOut]
    addenda: list[AddendumOut]
    # The draft or standing prescription first, then anything it replaced.
    prescriptions: list[PrescriptionOut]
    updated_at: dt.datetime
    can_edit: bool
    can_add_addendum: bool


class ConsultationPage(BaseModel):
    items: list[ConsultationSummary]
    total: int
