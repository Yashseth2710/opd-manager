"""Request and response shapes for lab orders and their results."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.appointment import DoctorRef, PatientRef

LabStatus = Literal["ordered", "resulted", "reviewed", "cancelled"]
# High and low for a number outside its range, abnormal for a word that is
# not the one it should be.
Judgement = Literal["high", "low", "abnormal"]

# A panel as long as any a clinic sends out, with room to spare.
MAX_VALUES = 40
# More tests than this on one visit is a slip somewhere, not a work-up.
MAX_PER_VISIT = 30


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class LabOrderIn(_Trimmed):
    consultation_id: uuid.UUID
    # From the list of common tests. Without it, the name is what was typed.
    test_code: str | None = Field(default=None, max_length=40)
    test_name: str | None = Field(default=None, max_length=120)
    urgent: bool = False
    instructions: str | None = Field(default=None, max_length=300)


class LabCancel(_Trimmed):
    reason: str = Field(min_length=1, max_length=200)


class ResultValueIn(_Trimmed):
    name: str = Field(min_length=1, max_length=80)
    value: str = Field(default="", max_length=60)
    unit: str | None = Field(default=None, max_length=24)
    low: Decimal | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    high: Decimal | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    expected: str | None = Field(default=None, max_length=40)


class LabResultIn(_Trimmed):
    """The whole report at once. Sending it again replaces what was there."""

    reported_on: dt.date
    lab_name: str | None = Field(default=None, max_length=120)
    findings: str | None = Field(default=None, max_length=5000)
    values: list[ResultValueIn] = Field(default_factory=list, max_length=MAX_VALUES)


class ResultValueOut(BaseModel):
    name: str
    value: str
    unit: str | None
    low: float | None
    high: float | None
    expected: str | None
    flag: Judgement | None


class Earlier(BaseModel):
    """The same value on this patient's last report of the same test."""

    value: str
    flag: Judgement | None
    reported_on: dt.date


class ReportedValue(ResultValueOut):
    earlier: Earlier | None


class TemplateValue(BaseModel):
    """A line to fill in, with the range for this patient where one is known."""

    name: str
    unit: str | None
    low: float | None
    high: float | None
    expected: str | None


class LabOrderBrief(BaseModel):
    id: uuid.UUID
    order_number: str
    test_code: str | None
    test_name: str
    category: str | None
    urgent: bool
    instructions: str | None
    status: LabStatus
    ordered_at: dt.datetime
    reported_on: dt.date | None
    # How many values on the report are outside their range.
    flagged: int
    consultation_id: uuid.UUID


class LabOrderListed(LabOrderBrief):
    patient: PatientRef
    doctor: DoctorRef


class LabOrderOut(LabOrderListed):
    ordered_by: str | None
    cancelled_at: dt.datetime | None
    cancelled_by: str | None
    cancel_reason: str | None
    lab_name: str | None
    findings: str | None
    values: list[ReportedValue]
    resulted_at: dt.datetime | None
    resulted_by: str | None
    changed_by: str | None
    reviewed_at: dt.datetime | None
    reviewed_by: str | None
    # The lines a report of this test usually has, for typing one in. Empty
    # for a test the clinic typed itself, or one whose report is only words.
    template: list[TemplateValue]
    # Ranges were left out of the template because the patient is a child,
    # or their sex is not recorded, and the lab's own will be on the report.
    ranges_left_out: bool
    visit_date: dt.date
    ordered_on: dt.date
    clinic_today: dt.date
    visit_open: bool
    can_enter: bool
    can_review: bool
    can_cancel: bool
    can_remove: bool


class LabOrderPage(BaseModel):
    items: list[LabOrderListed]
    total: int
    # Each status across the clinic, or the one doctor asked about, whatever
    # else was filtered on, for the tabs.
    counts: dict[str, int]


class LabTestOut(BaseModel):
    code: str | None
    name: str
    also: list[str]
    category: str | None
    prepare: str | None
    # Values a report of it carries; none for a report that is only words.
    parts: int
    times_ordered: int


class LabCatalogue(BaseModel):
    categories: dict[str, str]
    tests: list[LabTestOut]


class Removed(BaseModel):
    removed: bool = True
