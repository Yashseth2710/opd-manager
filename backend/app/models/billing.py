"""Bills: what a visit cost, and the money that came in against it.

A bill starts as a draft the desk can change freely. Issuing it gives it the
clinic's next number for the financial year and fixes what it says, because
a copy may already be in the patient's hand. From then on it is paid, in one
go or in parts, and anything wrong with it is put right by voiding it and
raising another, never by editing the one that was handed over.

Money only moves forward. A payment is never edited or removed; money given
back is a refund, recorded beside it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

DRAFT = "draft"
UNPAID = "unpaid"
PARTLY_PAID = "partly_paid"
PAID = "paid"
REFUNDED = "refunded"
VOID = "void"
STATUSES = (DRAFT, UNPAID, PARTLY_PAID, PAID, REFUNDED, VOID)
# Issued and still owed something.
OWED = (UNPAID, PARTLY_PAID)

ITEM_TYPES = ("consultation", "procedure", "lab", "medicine", "other")

PAYMENT = "payment"
REFUND = "refund"
KINDS = (PAYMENT, REFUND)
METHODS = ("cash", "upi", "card", "bank_transfer", "cheque", "other")


def _listed(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))


class Invoice(TimestampMixin, TenantRow):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(f"status IN ({_listed(STATUSES)})", name="ck_invoice_status"),
        # The sums hold in the database, whatever the code that wrote them.
        CheckConstraint(
            "total = subtotal - discount_amount + tax_amount", name="ck_invoice_total"
        ),
        CheckConstraint("balance = total - amount_paid", name="ck_invoice_balance"),
        CheckConstraint(
            "discount_amount >= 0 AND discount_amount <= subtotal", name="ck_invoice_discount"
        ),
        CheckConstraint("tax_amount >= 0", name="ck_invoice_tax"),
        CheckConstraint(
            "tax_percent >= 0 AND tax_percent <= 100", name="ck_invoice_tax_percent"
        ),
        CheckConstraint(
            "amount_paid >= 0 AND amount_paid <= total", name="ck_invoice_amount_paid"
        ),
        CheckConstraint(
            "refunded_amount >= 0 AND refunded_amount <= amount_paid",
            name="ck_invoice_refunded",
        ),
        CheckConstraint(
            "(status = 'draft') = (invoice_number IS NULL)", name="ck_invoice_number"
        ),
        CheckConstraint(
            "(status = 'draft') = (issued_at IS NULL)", name="ck_invoice_issued_at"
        ),
        CheckConstraint("(status = 'void') = (voided_at IS NOT NULL)", name="ck_invoice_void"),
        # Nothing is taken on a draft, and a bill is voided only once any
        # money on it has gone back.
        CheckConstraint("status <> 'draft' OR amount_paid = 0", name="ck_invoice_draft_unpaid"),
        CheckConstraint(
            "status <> 'void' OR amount_paid = refunded_amount", name="ck_invoice_void_settled"
        ),
        CheckConstraint("status <> 'paid' OR balance = 0", name="ck_invoice_paid"),
        Index("uq_invoice_number", "organization_id", "invoice_number", unique=True),
        # One bill for one visit. Voiding it frees the visit for the bill
        # that replaces it.
        Index(
            "uq_invoice_visit",
            "queue_entry_id",
            unique=True,
            postgresql_where=text("queue_entry_id IS NOT NULL AND status <> 'void'"),
        ),
        # A second press of Save, or a retry after the network dropped, is
        # answered with the bill the first one made.
        Index(
            "uq_invoice_request",
            "organization_id",
            "request_key",
            unique=True,
            postgresql_where=text("request_key IS NOT NULL"),
        ),
        Index("ix_invoice_patient", "organization_id", "patient_id", "created_at"),
        Index("ix_invoice_visit", "queue_entry_id"),
        Index("ix_invoice_doctor", "organization_id", "doctor_id", "issued_at"),
        Index("ix_invoice_status", "organization_id", "status", "issued_at"),
        Index(
            "ix_invoice_owed",
            "organization_id",
            "issued_at",
            postgresql_where=text("status IN ('unpaid', 'partly_paid')"),
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    # The visit it is for, when it is for one. A bill for a dressing done
    # at the desk has none.
    queue_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opd_queue_entries.id", ondelete="SET NULL")
    )
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="SET NULL")
    )

    # INV/2026-27/0001, given when the bill is issued so a draft that is
    # thrown away leaves no gap in the numbers.
    invoice_number: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=DRAFT)

    subtotal: Mapped[Decimal] = _money()
    discount_amount: Mapped[Decimal] = _money()
    discount_reason: Mapped[str | None] = mapped_column(String(200))
    # The rate as it stood when the bill was made, so changing the clinic's
    # rate later does not rewrite old bills.
    tax_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00")
    )
    tax_amount: Mapped[Decimal] = _money()
    total: Mapped[Decimal] = _money()
    # Everything received, and of that, what has since been given back.
    amount_paid: Mapped[Decimal] = _money()
    refunded_amount: Mapped[Decimal] = _money()
    balance: Mapped[Decimal] = _money()

    # Printed on the bill.
    notes: Mapped[str | None] = mapped_column(String(500))

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    issued_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    voided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    void_reason: Mapped[str | None] = mapped_column(String(200))

    request_key: Mapped[str | None] = mapped_column(String(64))


class InvoiceItem(TenantRow):
    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint(f"item_type IN ({_listed(ITEM_TYPES)})", name="ck_invoice_item_type"),
        CheckConstraint("quantity BETWEEN 1 AND 999", name="ck_invoice_item_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_invoice_item_price"),
        CheckConstraint("amount = quantity * unit_price", name="ck_invoice_item_amount"),
        Index("ix_invoice_item_invoice", "invoice_id", "position"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class Payment(TenantRow):
    """Money in, or money given back. Never changed once written."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_listed(KINDS)})", name="ck_payment_kind"),
        CheckConstraint(f"method IN ({_listed(METHODS)})", name="ck_payment_method"),
        CheckConstraint("amount > 0", name="ck_payment_amount"),
        CheckConstraint(
            "kind <> 'refund' OR note IS NOT NULL", name="ck_payment_refund_reason"
        ),
        Index(
            "uq_payment_request",
            "organization_id",
            "request_key",
            unique=True,
            postgresql_where=text("request_key IS NOT NULL"),
        ),
        Index("ix_payment_invoice", "invoice_id", "received_at"),
        Index("ix_payment_day", "organization_id", "received_at"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default=PAYMENT)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    # The UPI or card reference, or the cheque number.
    reference: Mapped[str | None] = mapped_column(String(60))
    # Why, for a refund. Anything worth saying, for a payment.
    note: Mapped[str | None] = mapped_column(String(200))
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    request_key: Mapped[str | None] = mapped_column(String(64))
