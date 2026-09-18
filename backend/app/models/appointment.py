"""Appointments, and the record of everything that happened to each one.

The rule that matters most here is held by the database rather than by the
code that books: one doctor, one patient, one chair at a time. Two
receptionists clicking the same slot at the same moment both pass any check
the application makes before writing, and only one of them can win against
an exclusion constraint.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

SCHEDULED = "scheduled"
CONFIRMED = "confirmed"
CHECKED_IN = "checked_in"
WAITING = "waiting"
IN_CONSULTATION = "in_consultation"
COMPLETED = "completed"
CANCELLED = "cancelled"
NO_SHOW = "no_show"

STATUSES = (
    SCHEDULED,
    CONFIRMED,
    CHECKED_IN,
    WAITING,
    IN_CONSULTATION,
    COMPLETED,
    CANCELLED,
    NO_SHOW,
)

# The two ways an appointment stops holding its slot. Everything else, a
# finished consultation included, still occupied that time.
RELEASED = (CANCELLED, NO_SHOW)

# Still ahead of the patient and still movable.
OPEN = (SCHEDULED, CONFIRMED)

CONSULTATION = "consultation"
FOLLOW_UP = "follow_up"
TYPES = (CONSULTATION, FOLLOW_UP)

# How it reached the desk. Walk-ins join the queue rather than the book.
BY_PHONE = "phone"
AT_DESK = "desk"
SOURCES = (BY_PHONE, AT_DESK)

_HOLDS_ITS_SLOT = text("status NOT IN ('cancelled', 'no_show')")


def _listed(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _one_at_a_time(column: str) -> ExcludeConstraint:
    """No two bookings for the same person overlapping in time.

    Half-open ranges, so an appointment ending at ten and the next starting
    at ten do not collide. Cancelled and missed ones give their time back.
    """
    # SQLAlchemy ships this constructor without annotations.
    return ExcludeConstraint(  # type: ignore[no-untyped-call]
        (text(column), "="),
        (text("tstzrange(scheduled_start, scheduled_end)"), "&&"),
        name=f"ex_appointments_{column.removesuffix('_id')}_overlap",
        using="gist",
        where=_HOLDS_ITS_SLOT,
    )


class Appointment(TimestampMixin, TenantRow):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("scheduled_end > scheduled_start", name="ck_appointments_order"),
        CheckConstraint(f"status IN ({_listed(STATUSES)})", name="ck_appointments_status"),
        CheckConstraint(f"appointment_type IN ({_listed(TYPES)})", name="ck_appointments_type"),
        CheckConstraint(f"source IN ({_listed(SOURCES)})", name="ck_appointments_source"),
        # A doctor in two consultations at once.
        _one_at_a_time("doctor_id"),
        # And a patient in two rooms at once, which no clinic means to book
        # however many doctors they see in a morning.
        _one_at_a_time("patient_id"),
        Index(
            "ix_appointments_doctor_start", "organization_id", "doctor_id", "scheduled_start"
        ),
        Index(
            "ix_appointments_patient_start", "organization_id", "patient_id", "scheduled_start"
        ),
        Index(
            "ix_appointments_open_start",
            "organization_id",
            "scheduled_start",
            postgresql_where=text("status NOT IN ('cancelled', 'no_show', 'completed')"),
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )

    # Instants, worked out from the clinic's date and wall-clock time when it
    # was booked. The wall-clock view is derived again on the way out.
    scheduled_start: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scheduled_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    appointment_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CONSULTATION
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=AT_DESK)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SCHEDULED)

    # What the patient says it is about, in their words, for the doctor.
    reason: Mapped[str | None] = mapped_column(String(200))
    # For the desk: "bring last month's reports", "needs a wheelchair".
    notes: Mapped[str | None] = mapped_column(Text)

    cancelled_reason: Mapped[str | None] = mapped_column(String(200))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    booked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    @property
    def holds_its_slot(self) -> bool:
        return self.status not in RELEASED

    @property
    def is_open(self) -> bool:
        return self.status in OPEN


# What the history records. A status change is most of it, but moving an
# appointment to another time is worth a line too, and changes no status.
BOOKED = "booked"
CONFIRMED_EVENT = "confirmed"
RESCHEDULED = "rescheduled"
CANCELLED_EVENT = "cancelled"
MARKED_NO_SHOW = "no_show"
EDITED = "edited"
EVENTS = (BOOKED, CONFIRMED_EVENT, RESCHEDULED, CANCELLED_EVENT, MARKED_NO_SHOW, EDITED)


class AppointmentEvent(TenantRow):
    """One line in an appointment's history, written and never changed.

    Carries the name of whoever did it as it was at the time, so the history
    stays readable after that person has left the clinic.
    """

    __tablename__ = "appointment_status_history"
    __table_args__ = (
        CheckConstraint(f"event IN ({_listed(EVENTS)})", name="ck_appointment_history_event"),
        Index("ix_appointment_history_appointment", "organization_id", "appointment_id"),
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    # A sentence for the timeline: "Moved from Mon 22 Sep, 9:00 am".
    detail: Mapped[str | None] = mapped_column(String(300))

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_name: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
