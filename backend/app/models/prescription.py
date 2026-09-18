"""Prescriptions, and the list of medicines doctors pick them from.

A prescription is written alongside the visit's notes and issued when the
visit is finished: numbered, dated, and never changed after that. A mistake
found later is put right with a new prescription that replaces the old one,
so both stay on record and the one a pharmacy was handed can always be read
back exactly as it was.
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
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantRow, TimestampMixin, UUIDMixin

DRAFT = "draft"
ISSUED = "issued"
REPLACED = "replaced"
STATUSES = (DRAFT, ISSUED, REPLACED)

BEFORE_FOOD = "before_food"
AFTER_FOOD = "after_food"
WITH_FOOD = "with_food"
EMPTY_STOMACH = "empty_stomach"
BEDTIME = "bedtime"
AS_NEEDED = "as_needed"
TIMINGS = (BEFORE_FOOD, AFTER_FOOD, WITH_FOOD, EMPTY_STOMACH, BEDTIME, AS_NEEDED)

NLEM_2022 = "nlem-2022"


def _listed(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Medicine(UUIDMixin, Base):
    """One medicine in one presentation, from a published list. Shared by every
    clinic and changed only by a migration, never through the application."""

    __tablename__ = "medicines"
    __table_args__ = (
        Index(
            "uq_medicine_presentation",
            text("lower(name)"),
            text("coalesce(lower(presentation), '')"),
            unique=True,
        ),
        Index(
            "ix_medicines_name_trgm",
            text("lower(name) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # "Tablet 500 mg", as the list prints it. Empty for the few that are
    # listed only by name.
    presentation: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(24), nullable=False)


class Prescription(TimestampMixin, TenantRow):
    __tablename__ = "prescriptions"
    __table_args__ = (
        CheckConstraint(f"status IN ({_listed(STATUSES)})", name="ck_prescription_status"),
        CheckConstraint(
            "(status = 'draft') = (prescription_number IS NULL)",
            name="ck_prescription_numbered_once_issued",
        ),
        CheckConstraint(
            "(status = 'draft') = (issued_at IS NULL)", name="ck_prescription_issued_at"
        ),
        # One being written and one standing per visit. A correction replaces
        # the standing one rather than sitting beside it.
        Index(
            "uq_prescription_draft",
            "consultation_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        Index(
            "uq_prescription_issued",
            "consultation_id",
            unique=True,
            postgresql_where=text("status = 'issued'"),
        ),
        Index(
            "uq_prescription_number",
            "organization_id",
            "prescription_number",
            unique=True,
            postgresql_where=text("prescription_number IS NOT NULL"),
        ),
        Index("ix_prescription_patient", "organization_id", "patient_id", "issued_at"),
    )

    consultation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )

    prescription_number: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=DRAFT)
    # What the patient is told on the paper itself: diet, rest, when to come
    # back sooner. Separate from the notes, which the desk does not read.
    instructions: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[dt.date | None] = mapped_column(Date)

    replaces_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prescriptions.id", ondelete="SET NULL")
    )
    correction_reason: Mapped[str | None] = mapped_column(String(200))
    issued_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    @property
    def is_draft(self) -> bool:
        return self.status == DRAFT


class PrescriptionItem(TenantRow):
    """One medicine on a prescription, in the doctor's words. Picked from the
    list or typed, so the name is kept as written rather than as a link."""

    __tablename__ = "prescription_items"
    __table_args__ = (
        CheckConstraint(
            f"timing IS NULL OR timing IN ({_listed(TIMINGS)})", name="ck_prescription_timing"
        ),
        CheckConstraint(
            "duration_days IS NULL OR duration_days BETWEEN 1 AND 365",
            name="ck_prescription_duration",
        ),
        Index("ix_prescription_item_order", "prescription_id", "position"),
        Index("ix_prescription_item_name", "organization_id", text("lower(medicine_name)")),
    )

    prescription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False
    )
    medicine_name: Mapped[str] = mapped_column(String(200), nullable=False)
    presentation: Mapped[str | None] = mapped_column(String(200))
    # "1-0-1", "1 tablet", "5 mL". Free, because the ways of saying it are
    # many and a doctor will not be told how to write their own dose.
    dose: Mapped[str | None] = mapped_column(String(40))
    timing: Mapped[str | None] = mapped_column(String(16))
    duration_days: Mapped[int | None] = mapped_column(Integer)
    instructions: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
