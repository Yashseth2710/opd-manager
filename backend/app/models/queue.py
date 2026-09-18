"""The line outside each doctor's door, one day at a time.

A place in the queue is made when a patient arrives: checked in against
their appointment, or added as a walk-in with none. The token is the number
they hear called, counted per doctor and per clinic day, so it starts again
at one every morning.

The database holds the rules two desks could otherwise break between them:
nobody holds two places at once, and a doctor has one patient called and one
in the room, never two.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

WAITING = "waiting"
CALLED = "called"
IN_CONSULTATION = "in_consultation"
COMPLETED = "completed"
SKIPPED = "skipped"
NO_SHOW = "no_show"

STATUSES = (WAITING, CALLED, IN_CONSULTATION, COMPLETED, SKIPPED, NO_SHOW)

# Still in the building as far as the desk knows. A patient who missed their
# call is still here until somebody says they have gone.
LIVE = (WAITING, CALLED, IN_CONSULTATION, SKIPPED)

# Finished with, one way or the other.
DONE = (COMPLETED, NO_SHOW)

NORMAL = "normal"
URGENT = "urgent"
PRIORITIES = (NORMAL, URGENT)


def _listed(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _one_per_day(name: str, *columns: str, where: str) -> Index:
    return Index(
        name,
        "organization_id",
        *columns,
        "token_date",
        unique=True,
        postgresql_where=text(where),
    )


class QueueEntry(TimestampMixin, TenantRow):
    __tablename__ = "opd_queue_entries"
    __table_args__ = (
        CheckConstraint(f"status IN ({_listed(STATUSES)})", name="ck_queue_status"),
        CheckConstraint(f"priority IN ({_listed(PRIORITIES)})", name="ck_queue_priority"),
        CheckConstraint("token_number > 0", name="ck_queue_token"),
        UniqueConstraint(
            "organization_id", "doctor_id", "token_date", "token_number", name="uq_queue_token"
        ),
        # One place per appointment. Undoing a check-in removes the place,
        # so checking in again afterwards is not blocked by it.
        Index(
            "uq_queue_appointment",
            "appointment_id",
            unique=True,
            postgresql_where=text("appointment_id IS NOT NULL"),
        ),
        # A patient in two lines at once, which two desks checking the same
        # person in could otherwise manage between them.
        _one_per_day(
            "uq_queue_patient_live", "patient_id", where=f"status IN ({_listed(LIVE)})"
        ),
        # Keyed on the day, so a place somebody forgot to close last night
        # does not hold up this morning.
        _one_per_day("uq_queue_doctor_called", "doctor_id", where="status = 'called'"),
        _one_per_day(
            "uq_queue_doctor_in_room", "doctor_id", where="status = 'in_consultation'"
        ),
        Index("ix_queue_doctor_day", "organization_id", "doctor_id", "token_date", "status"),
    )

    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="CASCADE")
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )

    # The clinic's date, not the server's.
    token_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    token_number: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default=NORMAL)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=WAITING)

    # Why a walk-in came, for the doctor. A booked patient's reason stays on
    # the appointment.
    reason: Mapped[str | None] = mapped_column(String(200))

    checked_in_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    called_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    @property
    def is_walk_in(self) -> bool:
        return self.appointment_id is None
