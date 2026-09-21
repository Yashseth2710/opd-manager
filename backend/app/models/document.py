"""Files on a patient's record: a report from an outside lab, an X-ray, a
letter from the doctor who referred them.

The row holds what the file is and who put it there. The file itself lives in
the store, at an address nothing outside the API is ever given.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

LAB_REPORT = "lab_report"
CATEGORIES = (
    LAB_REPORT,
    "scan",
    "prescription",
    "referral",
    "discharge",
    "insurance",
    "other",
)
CONTENT_TYPES = ("application/pdf", "image/jpeg", "image/png", "image/webp")


def _listed(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class PatientDocument(TimestampMixin, TenantRow):
    __tablename__ = "patient_documents"
    __table_args__ = (
        CheckConstraint(f"category IN ({_listed(CATEGORIES)})", name="ck_document_category"),
        CheckConstraint(
            f"content_type IN ({_listed(CONTENT_TYPES)})", name="ck_document_content_type"
        ),
        CheckConstraint("size_bytes > 0", name="ck_document_size"),
        CheckConstraint(
            "lab_order_id IS NULL OR category = 'lab_report'", name="ck_document_lab_category"
        ),
        # The same file twice on one record is a double tap, not two
        # documents.
        Index("uq_document_per_patient", "patient_id", "sha256", unique=True),
        Index("ix_document_patient", "organization_id", "patient_id", "created_at"),
        Index("ix_document_visit", "consultation_id"),
        Index("ix_document_lab_order", "lab_order_id"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    # The visit it came in for, when there is one. A report that turns up
    # later still belongs to the visit that asked for it.
    consultation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consultations.id", ondelete="SET NULL")
    )
    # The lab's own copy of a report whose values are typed into an order.
    lab_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_orders.id", ondelete="SET NULL")
    )

    category: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    # The date on the paper, which for an old report brought in today is
    # not the day it was uploaded.
    dated: Mapped[dt.date | None] = mapped_column(Date)

    original_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Decided from the file's own bytes. What the browser said is kept
    # beside it and never acted on.
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    declared_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    blob_url: Mapped[str] = mapped_column(String(500), nullable=False)

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
