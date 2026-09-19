"""What the first page after signing in shows."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel

from app.schemas.appointment import DoctorRef, PatientRef
from app.schemas.queue import Priority, VitalsBrief


class Counts(BaseModel):
    # Appointments for today that were not cancelled.
    booked: int
    # Booked and not here yet, and of those, the ones past their time.
    to_come: int
    late: int
    # Of those seen, how many came without booking.
    walk_ins: int
    waiting: int
    with_doctor: int
    seen: int
    # Booked and never came, or left without being seen.
    no_shows: int


class InRoom(BaseModel):
    entry_id: uuid.UUID
    token: int
    patient: PatientRef
    minutes: int
    consultation_id: uuid.UUID | None


class Waiting(BaseModel):
    entry_id: uuid.UUID
    token: int
    patient: PatientRef
    doctor: DoctorRef
    priority: Priority
    reason: str | None
    waited_minutes: int
    vitals: VitalsBrief | None


class Lane(BaseModel):
    doctor: DoctorRef
    # Why nobody can join this doctor's line today, if nobody can.
    closed: str | None
    now_seeing: InRoom | None
    called: InRoom | None
    waiting: int
    longest_wait_minutes: int | None
    seen: int
    to_come: int
    average_minutes: int
    # Whoever comes through the door next: the one called, or the head of
    # the line in the order the queue runs it.
    next: Waiting | None


class Arrival(BaseModel):
    appointment_id: uuid.UUID
    patient: PatientRef
    doctor: DoctorRef
    start_time: dt.time
    is_late: bool


class DueBack(BaseModel):
    patient: PatientRef
    doctor: DoctorRef
    # The visit that asked them back.
    asked_on: dt.date
    consultation_id: uuid.UUID
    # Here today, booked for later today, or neither yet.
    state: Literal["here", "seen", "booked", "not_booked"]
    booked_for: dt.time | None


class Unfinished(BaseModel):
    consultation_id: uuid.UUID
    patient: PatientRef
    visit_date: dt.date
    chief_complaint: str | None


class ResultIn(BaseModel):
    """A lab report back for one of the doctor's patients, not yet looked at."""

    order_id: uuid.UUID
    patient: PatientRef
    test_name: str
    reported_on: dt.date
    urgent: bool
    # Values on it outside their range.
    flagged: int


class Today(BaseModel):
    date: dt.date
    day_name: str
    # The clinic as a whole, one doctor's own day, or a doctor's account
    # with no profile to show a day for.
    view: Literal["clinic", "doctor", "unlinked"]
    counts: Counts
    lanes: list[Lane]
    # Longest wait first.
    waiting: list[Waiting]
    waiting_total: int
    without_vitals: int
    # Soonest first.
    arrivals: list[Arrival]
    arrivals_total: int
    due_back: list[DueBack]
    unfinished: list[Unfinished]
    unfinished_total: int
    # Oldest first, for a doctor's own day.
    results: list[ResultIn]
    results_total: int
