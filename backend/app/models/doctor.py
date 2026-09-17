"""Doctors, the hours they sit, and the days they do not.

A doctor is a record of the clinic, not of an account. Visiting consultants
who come in on Thursdays need a profile, a fee and a schedule long before
anyone gives them a login, and some never get one. Where an account does
exist it is linked, and the link is what lets the consultation a doctor
signs be attributed to the person who signed it.
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
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

ACTIVE = "active"
INACTIVE = "inactive"

TITLES = ("Dr", "Prof", "Mr", "Ms", "Mrs")

# Monday first, matching how a weekly rota is read and written down. Python's
# date.weekday() agrees, which keeps the conversion at availability time to
# nothing at all.
MONDAY = 0
SUNDAY = 6
DAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class Doctor(TimestampMixin, TenantRow):
    __tablename__ = "doctors"
    __table_args__ = (
        # One account is one doctor. Without this a second profile could be
        # linked to the same login and every consultation would have two
        # plausible authors.
        Index(
            "uq_doctors_user",
            "organization_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        # A council registration number identifies one clinician. Two rows
        # carrying the same one is a duplicate profile, and a prescription
        # printed against the wrong one is a real-world problem.
        Index(
            "uq_doctors_registration",
            "organization_id",
            text("lower(registration_number)"),
            unique=True,
            postgresql_where=text("registration_number IS NOT NULL"),
        ),
        Index("ix_doctors_status_name", "organization_id", "status", "last_name"),
        Index(
            "ix_doctors_name_trgm",
            text("lower(first_name || ' ' || last_name) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )

    # Null for anyone who works here without signing in.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(String(8), nullable=False, default="Dr")
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)

    speciality: Mapped[str | None] = mapped_column(String(80))
    qualifications: Mapped[str | None] = mapped_column(String(160))
    registration_number: Mapped[str | None] = mapped_column(String(48))
    years_of_experience: Mapped[int | None] = mapped_column(SmallInteger)

    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    room: Mapped[str | None] = mapped_column(String(32))

    # What they can hold a consultation in. Asked at the desk often enough
    # to be worth a field rather than a line in the bio.
    languages: Mapped[list[str] | None] = mapped_column(JSONB)
    bio: Mapped[str | None] = mapped_column(Text)

    # Null means the clinic's figure applies, which is different from zero.
    # Storing a copy of the clinic default would freeze it at the moment the
    # profile was written and quietly stop following later changes.
    consultation_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    follow_up_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    slot_duration_minutes: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ACTIVE)
    deactivated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_name(self) -> str:
        return f"{self.title} {self.full_name}".strip()

    @property
    def is_active(self) -> bool:
        return self.status == ACTIVE


class DoctorSchedule(TenantRow):
    """One block of a recurring week: Tuesday morning, Tuesday evening.

    Several rows per day is the normal case rather than the exception — an
    OPD that runs nine to one and five to eight is two blocks, not one long
    one with a four-hour break in it.

    No timestamps: a schedule is replaced whole rather than edited row by
    row, so a per-row created_at would only ever record the last replacement.
    """

    __tablename__ = "doctor_schedules"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_doctor_schedules_order"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_doctor_schedules_day_of_week"),
        CheckConstraint(
            "(break_start IS NULL) = (break_end IS NULL)",
            name="ck_doctor_schedules_break_pair",
        ),
        CheckConstraint(
            "break_end IS NULL OR break_end > break_start",
            name="ck_doctor_schedules_break_order",
        ),
        Index("ix_doctor_schedules_doctor", "organization_id", "doctor_id", "day_of_week"),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )

    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Wall-clock in the clinic's timezone. A doctor who starts at nine starts
    # at nine in March and in November, which a stored instant would not.
    start_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[dt.time] = mapped_column(Time, nullable=False)

    break_start: Mapped[dt.time | None] = mapped_column(Time)
    break_end: Mapped[dt.time | None] = mapped_column(Time)

    slot_duration_minutes: Mapped[int | None] = mapped_column(Integer)


class DoctorLeave(TimestampMixin, TenantRow):
    """A dated exception to the week above.

    Times are optional, so one row covers both a fortnight in Kerala and the
    two hours somebody is at their child's school.
    """

    __tablename__ = "doctor_leaves"
    __table_args__ = (
        CheckConstraint("ends_on >= starts_on", name="ck_doctor_leaves_order"),
        CheckConstraint(
            "(start_time IS NULL) = (end_time IS NULL)", name="ck_doctor_leaves_time_pair"
        ),
        CheckConstraint(
            "end_time IS NULL OR end_time > start_time", name="ck_doctor_leaves_time_order"
        ),
        Index("ix_doctor_leaves_span", "organization_id", "doctor_id", "starts_on", "ends_on"),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )

    starts_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # Both null means whole days.
    start_time: Mapped[dt.time | None] = mapped_column(Time)
    end_time: Mapped[dt.time | None] = mapped_column(Time)

    reason: Mapped[str | None] = mapped_column(String(200))
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    @property
    def is_all_day(self) -> bool:
        return self.start_time is None
