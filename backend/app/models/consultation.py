"""What the doctor wrote about a visit.

A consultation is opened once a patient is in the room and belongs to the
doctor who saw them. It stays a draft while they write, saving as they go,
and is locked when they finish. Anything that comes to light afterwards is
added beneath it as a dated addendum rather than written over what was
there, because a note other people may already have acted on has to keep
saying what it said.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

DRAFT = "draft"
COMPLETED = "completed"
STATUSES = (DRAFT, COMPLETED)


class Consultation(TimestampMixin, TenantRow):
    __tablename__ = "consultations"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'completed')", name="ck_consultation_status"),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="ck_consultation_completed_at",
        ),
        CheckConstraint("version > 0", name="ck_consultation_version"),
        # One set of notes per place in the queue, so two tabs opening the
        # notes for the same patient land on the same draft.
        Index(
            "uq_consultation_queue_entry",
            "queue_entry_id",
            unique=True,
            postgresql_where=text("queue_entry_id IS NOT NULL"),
        ),
        Index("ix_consultation_patient", "organization_id", "patient_id", "started_at"),
        Index("ix_consultation_doctor", "organization_id", "doctor_id", "status", "started_at"),
    )

    queue_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opd_queue_entries.id", ondelete="SET NULL")
    )
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="SET NULL")
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )

    chief_complaint: Mapped[str | None] = mapped_column(String(500))
    history: Mapped[str | None] = mapped_column(Text)
    examination: Mapped[str | None] = mapped_column(Text)
    advice: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[dt.date | None] = mapped_column(Date)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DRAFT)
    # Counts saves. A save names the version it was written against, so a
    # second tab working from an older copy is refused instead of quietly
    # putting back what the first one had just replaced.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    written_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    @property
    def is_draft(self) -> bool:
        return self.status == DRAFT


class ConsultationDiagnosis(TenantRow):
    """One diagnosis on a visit, in the doctor's words. Several are allowed
    and one of them is the main reason for the visit."""

    __tablename__ = "consultation_diagnoses"
    __table_args__ = (
        Index(
            "uq_consultation_primary_diagnosis",
            "consultation_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        Index("ix_consultation_diagnosis_order", "consultation_id", "position"),
    )

    consultation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ConsultationAddendum(TenantRow):
    """Something added to finished notes. Never edited and never removed."""

    __tablename__ = "consultation_addenda"
    __table_args__ = (Index("ix_consultation_addendum", "consultation_id", "created_at"),)

    consultation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    written_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
