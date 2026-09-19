"""Lab tests: ordered by the doctor during the visit, reported back later.

An order is one test for one visit. It is written while the patient is in
the room, goes out to whichever lab the clinic sends to, and comes back as a
report somebody types in: the values with the ranges printed beside them, or
the words of a scan or an ECG. The doctor who asked for it then marks it
seen, and from then on the report reads the same for everyone who opens it.

Deliberately simple. Receiving results straight from a lab's own system is
a different product.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

ORDERED = "ordered"
RESULTED = "resulted"
REVIEWED = "reviewed"
CANCELLED = "cancelled"
STATUSES = (ORDERED, RESULTED, REVIEWED, CANCELLED)
# Still something the lab or the doctor has to act on.
OPEN = (ORDERED, RESULTED)


def _listed(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class LabOrder(TimestampMixin, TenantRow):
    __tablename__ = "lab_orders"
    __table_args__ = (
        CheckConstraint(f"status IN ({_listed(STATUSES)})", name="ck_lab_order_status"),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="ck_lab_order_cancelled_at",
        ),
        CheckConstraint(
            "(status IN ('resulted', 'reviewed')) = (resulted_at IS NOT NULL)",
            name="ck_lab_order_resulted_at",
        ),
        CheckConstraint(
            "(status = 'reviewed') = (reviewed_at IS NOT NULL)",
            name="ck_lab_order_reviewed_at",
        ),
        CheckConstraint(
            "resulted_at IS NULL OR reported_on IS NOT NULL",
            name="ck_lab_order_reported_on",
        ),
        # The same test twice on one visit is a slip, not two tests. One that
        # was called off can be asked for again.
        Index(
            "uq_lab_order_test_per_visit",
            "consultation_id",
            text("lower(test_name)"),
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
        Index("uq_lab_order_number", "organization_id", "order_number", unique=True),
        Index("ix_lab_order_patient", "organization_id", "patient_id", "ordered_at"),
        Index("ix_lab_order_status", "organization_id", "status", "ordered_at"),
        Index("ix_lab_order_doctor", "organization_id", "doctor_id", "status"),
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
    order_number: Mapped[str] = mapped_column(String(20), nullable=False)

    # The key into the clinic's list of common tests, when it came from
    # there. The name is kept as ordered either way, so a test the list does
    # not carry is ordered the same way as one it does.
    test_code: Mapped[str | None] = mapped_column(String(40))
    test_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str | None] = mapped_column(String(20))
    urgent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # For the patient or the lab: "Nothing to eat after 10 pm".
    instructions: Mapped[str | None] = mapped_column(String(300))

    status: Mapped[str] = mapped_column(String(12), nullable=False, default=ORDERED)
    ordered_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ordered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(200))

    # The date printed on the lab's report, which is the date the values
    # belong to, whenever somebody got round to typing them in.
    reported_on: Mapped[dt.date | None] = mapped_column(Date)
    lab_name: Mapped[str | None] = mapped_column(String(120))
    # What a scan or an ECG found, or the lab's comment under a panel.
    findings: Mapped[str | None] = mapped_column(Text)
    resulted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    resulted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class LabResultValue(TenantRow):
    """One line of a report: Haemoglobin, 11.2 g/dL, 12 to 15.

    The value is kept as written, because plenty of them are not numbers:
    "Negative", "1:160", "++". The range is the one printed on this report,
    since labs differ, and is kept as numbers so the value can be judged
    against it. A result that is a word is judged against the word it
    should be instead.
    """

    __tablename__ = "lab_result_values"
    __table_args__ = (
        CheckConstraint(
            "low IS NULL OR high IS NULL OR low <= high", name="ck_lab_result_range_order"
        ),
        Index("ix_lab_result_value_order", "lab_order_id", "position"),
    )

    lab_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_orders.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str] = mapped_column(String(60), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(24))
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    expected: Mapped[str | None] = mapped_column(String(40))
