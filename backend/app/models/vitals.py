"""Vital signs, measured before or during a visit.

Usually taken at the desk while the patient waits, sometimes by the doctor
in the room. A set is taken for one place in the queue, and there is one set
per visit: a reading taken again corrects the first rather than sitting
beside it.

The limits here are wide on purpose. They exist to catch a slipped finger,
120 typed as 1200, not to decide what is normal. That judgement is made when
the readings are shown, and never stops a reading being saved.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

FASTING = "fasting"
RANDOM = "random"
AFTER_MEAL = "after_meal"
GLUCOSE_TIMINGS = (FASTING, RANDOM, AFTER_MEAL)

# The readings a set can hold. At least one of them has to be there.
MEASURES = (
    "systolic_mmhg",
    "diastolic_mmhg",
    "pulse_bpm",
    "temperature_c",
    "spo2_percent",
    "respiratory_rate",
    "weight_kg",
    "height_cm",
    "glucose_mg_dl",
)

# Anything outside these is a typing mistake rather than a patient.
LIMITS: dict[str, tuple[float, float]] = {
    "systolic_mmhg": (50, 300),
    "diastolic_mmhg": (20, 200),
    "pulse_bpm": (20, 250),
    "temperature_c": (30, 45),
    "spo2_percent": (50, 100),
    "respiratory_rate": (4, 80),
    "weight_kg": (0.3, 400),
    "height_cm": (20, 250),
    "glucose_mg_dl": (10, 1000),
}


def _within(column: str) -> CheckConstraint:
    low, high = LIMITS[column]
    return CheckConstraint(
        f"{column} IS NULL OR {column} BETWEEN {low} AND {high}", name=f"ck_vitals_{column}"
    )


class Vitals(TimestampMixin, TenantRow):
    __tablename__ = "vitals"
    __table_args__ = (
        CheckConstraint(
            " OR ".join(f"{column} IS NOT NULL" for column in MEASURES),
            name="ck_vitals_something_measured",
        ),
        # A pressure is two numbers or none.
        CheckConstraint(
            "(systolic_mmhg IS NULL) = (diastolic_mmhg IS NULL)",
            name="ck_vitals_pressure_pair",
        ),
        CheckConstraint(
            "systolic_mmhg IS NULL OR diastolic_mmhg < systolic_mmhg",
            name="ck_vitals_pressure_order",
        ),
        CheckConstraint(
            "(glucose_mg_dl IS NULL) = (glucose_timing IS NULL)",
            name="ck_vitals_glucose_timing",
        ),
        CheckConstraint(
            "glucose_timing IS NULL OR glucose_timing IN ('fasting', 'random', 'after_meal')",
            name="ck_vitals_glucose_timing_known",
        ),
        *(_within(column) for column in MEASURES),
        UniqueConstraint("queue_entry_id", name="uq_vitals_queue_entry"),
        Index("ix_vitals_patient", "organization_id", "patient_id", "taken_at"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    # Taking a place back out of the queue is how the desk undoes checking in
    # the wrong person, so the readings taken for it go with it.
    queue_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opd_queue_entries.id", ondelete="CASCADE"),
        nullable=False,
    )

    systolic_mmhg: Mapped[int | None] = mapped_column(Integer)
    diastolic_mmhg: Mapped[int | None] = mapped_column(Integer)
    pulse_bpm: Mapped[int | None] = mapped_column(Integer)
    # Held in Celsius to two places, so a Fahrenheit reading to one place
    # comes back out exactly as it was typed.
    temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    spo2_percent: Mapped[int | None] = mapped_column(Integer)
    respiratory_rate: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    glucose_mg_dl: Mapped[int | None] = mapped_column(Integer)
    glucose_timing: Mapped[str | None] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(String(200))

    taken_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The clinic's date when they were taken, which is the day they can
    # still be corrected on.
    taken_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    taken_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
