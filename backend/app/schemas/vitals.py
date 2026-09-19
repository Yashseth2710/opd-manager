"""Request and response shapes for vital signs."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.vitals import LIMITS

GlucoseTiming = Literal["fasting", "random", "after_meal"]
Level = Literal["high", "low"]
BmiBand = Literal["underweight", "normal", "overweight", "obese"]


def _limited(column: str) -> Any:
    low, high = LIMITS[column]
    return Field(default=None, ge=low, le=high)


class Readings(BaseModel):
    """Every reading at once. One left out is one not taken, so a correction
    that clears a mistaken reading sends it as empty."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    systolic_mmhg: int | None = _limited("systolic_mmhg")
    diastolic_mmhg: int | None = _limited("diastolic_mmhg")
    pulse_bpm: int | None = _limited("pulse_bpm")
    temperature_c: Decimal | None = _limited("temperature_c")
    spo2_percent: int | None = _limited("spo2_percent")
    respiratory_rate: int | None = _limited("respiratory_rate")
    weight_kg: Decimal | None = _limited("weight_kg")
    height_cm: Decimal | None = _limited("height_cm")
    glucose_mg_dl: int | None = _limited("glucose_mg_dl")
    glucose_timing: GlucoseTiming | None = None
    note: str | None = Field(default=None, max_length=200)


class VitalsTaken(Readings):
    queue_entry_id: uuid.UUID


class VitalsOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    queue_entry_id: uuid.UUID
    systolic_mmhg: int | None
    diastolic_mmhg: int | None
    pulse_bpm: int | None
    temperature_c: float | None
    spo2_percent: int | None
    respiratory_rate: int | None
    weight_kg: float | None
    height_cm: float | None
    glucose_mg_dl: int | None
    glucose_timing: GlucoseTiming | None
    note: str | None
    # Worked out from the weight and height, for adults only: a child's is
    # read against a growth chart, which a single number cannot stand in for.
    bmi: float | None
    bmi_band: BmiBand | None
    # Readings outside the usual range, keyed by what was measured:
    # blood_pressure, pulse, temperature, spo2, respiratory_rate, glucose, bmi.
    flags: dict[str, Level]
    taken_at: dt.datetime
    taken_on: dt.date
    taken_by: str | None
    changed_by: str | None
    updated_at: dt.datetime
    can_change: bool


class VitalsPage(BaseModel):
    items: list[VitalsOut]
    total: int


class Removed(BaseModel):
    removed: bool = True
