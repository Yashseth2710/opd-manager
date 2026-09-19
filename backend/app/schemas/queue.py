"""Request and response shapes for the day's queue."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.appointment import AppointmentType, DoctorRef, PatientRef, Status

QueueStatus = Literal["waiting", "called", "in_consultation", "completed", "skipped", "no_show"]
Priority = Literal["normal", "urgent"]


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class WalkIn(_Trimmed):
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=200)
    priority: Priority = "normal"


class CheckIn(_Trimmed):
    priority: Priority = "normal"


class PriorityWrite(BaseModel):
    priority: Priority


class BookedFor(BaseModel):
    """The appointment a place came from, for the line that says so."""

    id: uuid.UUID
    start_time: dt.time
    end_time: dt.time
    appointment_type: AppointmentType
    reason: str | None
    status: Status


class VitalsBrief(BaseModel):
    """What the queue shows of the readings taken for a place."""

    id: uuid.UUID
    systolic_mmhg: int | None
    diastolic_mmhg: int | None
    pulse_bpm: int | None
    temperature_c: float | None
    spo2_percent: int | None
    weight_kg: float | None
    glucose_mg_dl: int | None
    flags: dict[str, Literal["high", "low"]]


class QueueEntryOut(BaseModel):
    id: uuid.UUID
    token: int
    status: QueueStatus
    priority: Priority
    patient: PatientRef
    doctor: DoctorRef
    appointment: BookedFor | None
    reason: str | None
    checked_in_at: dt.datetime
    called_at: dt.datetime | None
    started_at: dt.datetime | None
    completed_at: dt.datetime | None
    # Minutes since they arrived while they wait, and how long they waited
    # once they have gone in. Worked out on the server, whose clock the
    # timestamps came from.
    waited_minutes: int
    # Where they stand in the line, counting from one, while they wait.
    position: int | None
    # A guess from how long this doctor's consultations have been taking
    # today. Never stored, and never shown as more than roughly.
    expected_wait_minutes: int | None
    # The notes written for this place, once the doctor has opened them.
    consultation_id: uuid.UUID | None = None
    # The prescription issued at this visit, for the desk to print.
    prescription_id: uuid.UUID | None = None
    vitals: VitalsBrief | None = None


class Arrival(BaseModel):
    """An appointment today that has not been checked in yet."""

    id: uuid.UUID
    patient: PatientRef
    start_time: dt.time
    end_time: dt.time
    appointment_type: AppointmentType
    status: Status
    reason: str | None
    is_late: bool


class Lane(BaseModel):
    doctor: DoctorRef
    # Why nobody can join this doctor's line today, if nobody can.
    closed: str | None
    now_seeing: QueueEntryOut | None
    called: QueueEntryOut | None
    waiting: list[QueueEntryOut]
    skipped: list[QueueEntryOut]
    done: list[QueueEntryOut]
    expected: list[Arrival]
    seen_count: int
    average_minutes: int


class QueueDay(BaseModel):
    date: dt.date
    day_name: str
    lanes: list[Lane]
    only_doctor_id: uuid.UUID | None
    unlinked: bool
