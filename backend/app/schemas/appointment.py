"""Request and response shapes for booking and managing appointments."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AppointmentType = Literal["consultation", "follow_up"]
Source = Literal["phone", "desk"]
Status = Literal[
    "scheduled",
    "confirmed",
    "checked_in",
    "waiting",
    "in_consultation",
    "completed",
    "cancelled",
    "no_show",
]


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentCreate(_Trimmed):
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    # The clinic's date and wall-clock time, the way the slot was shown. The
    # server turns them into an instant in the clinic's timezone, so a browser
    # in another one cannot book the wrong hour.
    date: dt.date
    start_time: dt.time
    appointment_type: AppointmentType = "consultation"
    source: Source = "desk"
    reason: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class AppointmentUpdate(_Trimmed):
    """Moving an appointment and correcting its details share one route.

    Timing fields that are left out keep their current value, so a change of
    doctor at the same hour needs only the doctor.
    """

    doctor_id: uuid.UUID | None = None
    date: dt.date | None = None
    start_time: dt.time | None = None
    appointment_type: AppointmentType | None = None
    source: Source | None = None
    reason: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class CancelWrite(_Trimmed):
    reason: str | None = Field(default=None, max_length=200)


class PatientRef(BaseModel):
    id: uuid.UUID
    patient_number: str
    full_name: str
    preferred_name: str | None
    phone: str | None
    age: str | None
    gender: str | None
    status: str
    allergy_count: int


class DoctorRef(BaseModel):
    id: uuid.UUID
    display_name: str
    speciality: str | None
    room: str | None
    status: str


class AppointmentOut(BaseModel):
    id: uuid.UUID
    patient: PatientRef
    doctor: DoctorRef

    # The clinic's wall clock, which is what the screen shows.
    date: dt.date
    start_time: dt.time
    end_time: dt.time
    scheduled_start: dt.datetime
    scheduled_end: dt.datetime

    appointment_type: AppointmentType
    source: Source
    status: Status
    reason: str | None
    notes: str | None
    # What this visit costs under the doctor's fees as they stand today.
    fee: str

    cancelled_reason: str | None
    cancelled_at: dt.datetime | None
    booked_by_name: str | None
    created_at: dt.datetime

    # Worked out against the clinic's clock rather than the browser's.
    has_started: bool
    is_over: bool
    # The clinic's today, which is the only day anybody can check in for.
    is_today: bool
    # Something about the doctor's week that no longer fits this booking,
    # said in a sentence: leave taken since, hours changed, stood down.
    conflict: str | None = None
    # The number they were given at check-in, once they have one.
    queue_token: int | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event: str
    from_status: str | None
    to_status: str
    detail: str | None
    actor_name: str | None
    created_at: dt.datetime


class AppointmentDetail(AppointmentOut):
    history: list[EventOut]
    # The notes written at this visit. Only an id: whether the caller may
    # read them is for the notes themselves to say.
    consultation_id: uuid.UUID | None = None


class AppointmentDay(BaseModel):
    date: dt.date
    day_name: str
    is_today: bool
    items: list[AppointmentOut]
    # Set when the caller only ever sees one doctor's list, their own.
    only_doctor_id: uuid.UUID | None
    # A doctor's account that no profile has been linked to yet sees nothing,
    # and the screen should say why rather than show an empty day.
    unlinked: bool


class PatientAppointments(BaseModel):
    upcoming: list[AppointmentOut]
    history: list[AppointmentOut]
