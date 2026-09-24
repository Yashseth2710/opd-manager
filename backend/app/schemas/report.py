"""What the reports page shows."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel

from app.schemas.appointment import DoctorRef
from app.schemas.billing import MethodTotal, Rupees

Range = Literal["today", "week", "month", "this_month", "last_month", "custom"]


class Span(BaseModel):
    """The days asked about, as the clinic counts them."""

    range: Range
    first_day: dt.date
    last_day: dt.date
    days: int
    label: str


class DayLine(BaseModel):
    date: dt.date
    seen: int
    # Of those seen, the ones who came without an appointment.
    walk_ins: int
    no_shows: int
    # Patients whose record was opened that day.
    registered: int
    # Taken that day, less anything given back out of it.
    collected: Rupees


class DoctorLine(BaseModel):
    doctor: DoctorRef
    seen: int
    no_shows: int
    # How long a visit took, or nothing when none were timed.
    average_minutes: int | None
    billed: Rupees
    collected: Rupees


class HourLine(BaseModel):
    hour: int
    seen: int


class TestLine(BaseModel):
    name: str
    times: int


class ChargeLine(BaseModel):
    description: str
    times: int
    amount: Rupees


class Before(BaseModel):
    """The stretch of the same length immediately before this one."""

    seen: int
    collected: Rupees


class Report(BaseModel):
    span: Span
    # The clinic as a whole, one doctor's own work, or a doctor's account
    # with no profile to report on.
    view: Literal["clinic", "doctor", "unlinked"]
    doctor: DoctorRef | None
    currency: str

    seen: int
    walk_ins: int
    no_shows: int
    new_patients: int
    # What each patient seen was worth, on average.
    per_patient: Rupees
    before: Before

    methods: list[MethodTotal]
    received: Rupees
    refunded: Rupees
    net: Rupees
    # Of what came in, the part paid from a link rather than at the desk.
    online: Rupees
    bills_issued: int
    billed: Rupees
    # Still owed on issued bills, whenever they were raised.
    outstanding: Rupees
    outstanding_bills: int

    # Every day in the stretch, including the ones nothing happened on.
    days: list[DayLine]
    doctors: list[DoctorLine]
    hours: list[HourLine]
    tests: list[TestLine]
    charges: list[ChargeLine]
