"""Bills for visits, and the money taken against them.

The desk raises a bill, usually for a visit and usually from what the visit
suggests: the doctor's fee, or their follow-up fee when the patient was seen
by them a few days before. It can be kept as a draft while the patient finds
their wallet, and is issued with the clinic's next number for the financial
year, after which it says what it said when it was handed over.

Payment comes in one go or in parts, by cash, UPI, card or anything else.
Every sum on the bill is worked out here and checked again by the database,
so a total and what makes it up cannot drift apart.

Money given back is a refund, which only the clinic admin makes, and a bill
is voided only once nothing is left taken on it: a void that left money
unaccounted for would be a hole in the drawer nobody could explain.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound, PermissionDenied, ValidationFailed
from app.core.permissions import OWNER
from app.models import (
    Appointment,
    Invoice,
    LabOrder,
    Organization,
    Patient,
    PatientAllergy,
    Payment,
    QueueEntry,
    User,
    billing,
    lab,
    queue,
)
from app.models.appointment import FOLLOW_UP
from app.models.counter import INVOICE
from app.repositories.billing import Billed, InvoiceRepository, PaymentRepository
from app.repositories.counters import next_in_sequence
from app.repositories.patients import PatientRepository
from app.repositories.queue import Placed, QueueRepository
from app.schemas.billing import (
    MAX_TOTAL,
    InvoiceChange,
    InvoiceIn,
    LineIn,
    PaymentIn,
    RefundIn,
)
from app.services.doctors import clinic_today, clinic_zone, effective_fee
from app.services.patients import PatientArchived, PatientNotFound
from app.services.queue import doctor_ref, patient_ref

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
# Sent by the web app with anything that takes money, so that pressing twice,
# or a retry after the connection dropped, does not take it twice.
REQUEST_KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class InvoiceNotFound(NotFound):
    code = "BILLING_INVOICE_NOT_FOUND"
    message = "That bill could not be found."


class Locked(AppError):
    code = "BILLING_LOCKED"
    status = 409
    message = "This bill has been issued, so it stays as it was handed over."


class AlreadyBilled(AppError):
    code = "BILLING_ALREADY_BILLED"
    status = 409
    message = "This visit already has a bill."

    def __init__(self, existing: Invoice) -> None:
        number = existing.invoice_number
        super().__init__(
            f"This visit already has a bill, {number}."
            if number
            else "This visit already has a bill, still a draft."
        )
        self.candidates = [
            {"id": str(existing.id), "invoice_number": number, "status": existing.status}
        ]


class AlreadyPaid(AppError):
    code = "BILLING_ALREADY_PAID"
    status = 409
    message = "This bill is paid in full."


class Voided(AppError):
    code = "BILLING_INVOICE_VOIDED"
    status = 409
    message = "This bill has been voided."


class Refunded(AppError):
    code = "BILLING_REFUNDED"
    status = 409
    message = (
        "Money has been given back on this bill, so it takes no more payments. "
        "Raise a new bill for anything still owed."
    )


class HasPayments(AppError):
    code = "BILLING_HAS_PAYMENTS"
    status = 409
    message = "Money has been taken on this bill. Give it back before voiding it."


def _invalid(
    field: str, sentence: str, code: str = "BILLING_INVALID_TOTAL"
) -> ValidationFailed:
    error = ValidationFailed({field: sentence}, sentence)
    error.code = code
    return error


def rupees(value: Decimal) -> str:
    """ "₹1,250.00", grouped the Indian way, for sentences the desk reads."""
    whole, _, paise = f"{value:.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}₹{whole}.{paise}"


def request_key(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    key = raw.strip()
    if not REQUEST_KEY.fullmatch(key):
        raise ValidationFailed(
            {"idempotency_key": "Send 8 to 64 letters, digits, dashes or underscores."}
        )
    return key


def financial_year(day: dt.date) -> str:
    """ "2026-27". An Indian financial year runs April to March, and bill
    numbers start again with each one."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _prefix(clinic: Organization) -> str:
    configured = str(clinic.effective_settings.get("invoice_prefix") or "INV").strip()
    return configured or "INV"


def _tax_percent(clinic: Organization) -> Decimal:
    try:
        rate = Decimal(str(clinic.effective_settings.get("tax_percent") or "0"))
    except ArithmeticError:
        return ZERO
    return min(max(rate, ZERO), Decimal(100)).quantize(CENT)


def _blank(value: str | None) -> str | None:
    return value if value else None


# --- Sums ------------------------------------------------------------------------


def _lines(items: list[LineIn]) -> list[dict[str, Any]]:
    return [
        {
            "item_type": item.item_type,
            "description": " ".join(item.description.split()),
            "quantity": item.quantity,
            "unit_price": item.unit_price.quantize(CENT),
            "amount": (item.unit_price * item.quantity).quantize(CENT),
        }
        for item in items
    ]


def _figure(
    invoice: Invoice,
    lines: list[dict[str, Any]],
    *,
    discount: Decimal,
    reason: str | None,
) -> None:
    """Works the bill out from its lines, and refuses one that does not add up."""
    subtotal = sum((line["amount"] for line in lines), ZERO)
    discount = discount.quantize(CENT)
    if subtotal > MAX_TOTAL:
        raise _invalid(
            "items", f"That comes to {rupees(subtotal)}, more than one bill can hold."
        )
    if discount > subtotal:
        raise _invalid(
            "discount_amount",
            f"The discount is more than the bill, which comes to {rupees(subtotal)}.",
        )
    if discount > 0 and not reason:
        raise _invalid(
            "discount_reason", "Say why there is a discount.", code="VALIDATION_ERROR"
        )
    taxable = subtotal - discount
    tax = (taxable * invoice.tax_percent / 100).quantize(CENT, rounding=ROUND_HALF_UP)

    invoice.subtotal = subtotal
    invoice.discount_amount = discount
    invoice.discount_reason = reason if discount > 0 else None
    invoice.tax_amount = tax
    invoice.total = taxable + tax
    invoice.balance = invoice.total - invoice.amount_paid


def _settle(invoice: Invoice) -> None:
    """The status that follows from the money, for a bill already issued."""
    invoice.balance = invoice.total - invoice.amount_paid
    if invoice.refunded_amount > 0 and invoice.refunded_amount == invoice.amount_paid:
        invoice.status = billing.REFUNDED
    elif invoice.balance == 0:
        invoice.status = billing.PAID
    elif invoice.amount_paid > 0:
        invoice.status = billing.PARTLY_PAID
    else:
        invoice.status = billing.UNPAID


# --- Raising a bill ------------------------------------------------------------------


async def _visit(
    session: AsyncSession, organization_id: uuid.UUID, entry_id: uuid.UUID
) -> Placed:
    placed = await QueueRepository(session, organization_id).one(entry_id)
    if placed is None:
        raise ValidationFailed({"queue_entry_id": "That visit could not be found."})
    return placed


async def _patient(
    session: AsyncSession, organization_id: uuid.UUID, patient_id: uuid.UUID
) -> Patient:
    patient = await PatientRepository(session, organization_id).get(patient_id)
    if patient is None:
        raise PatientNotFound
    return patient


async def create(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    actor_id: uuid.UUID,
    body: InvoiceIn,
    key: str | None,
) -> tuple[uuid.UUID, bool]:
    """The new bill's id, and whether it was made now rather than found
    from an earlier try of the same request."""
    repository = InvoiceRepository(session, organization_id)
    if key is not None:
        earlier = await repository.by_request(key)
        if earlier is not None:
            return earlier.id, False

    patient = await _patient(session, organization_id, body.patient_id)
    if patient.is_archived:
        raise PatientArchived("This record is archived. Restore it before raising a bill.")

    doctor_id: uuid.UUID | None = None
    if body.queue_entry_id is not None:
        placed = await _visit(session, organization_id, body.queue_entry_id)
        if placed.patient.id != patient.id:
            raise ValidationFailed({"queue_entry_id": "That visit is someone else's."})
        existing = await repository.live_for_visit(placed.entry.id)
        if existing is not None:
            raise AlreadyBilled(existing)
        doctor_id = placed.doctor.id

    invoice = Invoice(
        patient_id=patient.id,
        queue_entry_id=body.queue_entry_id,
        doctor_id=doctor_id,
        status=billing.DRAFT,
        tax_percent=_tax_percent(clinic),
        amount_paid=ZERO,
        refunded_amount=ZERO,
        notes=_blank(body.notes),
        created_by_id=actor_id,
        request_key=key,
    )
    lines = _lines(body.items)
    _figure(invoice, lines, discount=body.discount_amount, reason=_blank(body.discount_reason))

    try:
        async with session.begin_nested():
            await repository.add(invoice)
    except IntegrityError as exc:
        # Two desks billing one visit at once, or the same request twice.
        if key is not None:
            earlier = await repository.by_request(key)
            if earlier is not None:
                return earlier.id, False
        if body.queue_entry_id is not None:
            existing = await repository.live_for_visit(body.queue_entry_id)
            if existing is not None:
                raise AlreadyBilled(existing) from exc
        raise
    await repository.replace_items(invoice.id, lines)
    if body.issue:
        await _issue(session, organization_id, clinic, invoice, actor_id)
    return invoice.id, True


async def _locked(
    session: AsyncSession, organization_id: uuid.UUID, invoice_id: uuid.UUID
) -> Billed:
    found = await InvoiceRepository(session, organization_id).one(invoice_id, lock=True)
    if found is None:
        raise InvoiceNotFound
    return found


def _require_draft(invoice: Invoice) -> None:
    if invoice.status == billing.VOID:
        raise Voided
    if invoice.status != billing.DRAFT:
        raise Locked


async def change(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    invoice_id: uuid.UUID,
    body: InvoiceChange,
) -> None:
    found = await _locked(session, organization_id, invoice_id)
    invoice = found.invoice
    _require_draft(invoice)
    sent = body.model_fields_set

    if "notes" in sent:
        invoice.notes = _blank(body.notes)
    lines = (
        _lines(body.items)
        if body.items is not None
        else [
            {
                "item_type": item.item_type,
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "amount": item.amount,
            }
            for item in found.items
        ]
    )
    discount = (
        body.discount_amount
        if "discount_amount" in sent and body.discount_amount is not None
        else invoice.discount_amount
    )
    reason = (
        _blank(body.discount_reason) if "discount_reason" in sent else invoice.discount_reason
    )
    _figure(invoice, lines, discount=discount, reason=reason)
    if body.items is not None:
        await InvoiceRepository(session, organization_id).replace_items(invoice.id, lines)
    await session.flush()


async def _issue(
    session: AsyncSession,
    organization_id: uuid.UUID,
    clinic: Organization,
    invoice: Invoice,
    actor_id: uuid.UUID,
) -> None:
    year = financial_year(clinic_today(clinic))
    sequence = await next_in_sequence(session, organization_id, f"{INVOICE}:{year}")
    invoice.invoice_number = f"{_prefix(clinic)}/{year}/{sequence:04d}"
    invoice.issued_at = dt.datetime.now(dt.UTC)
    invoice.issued_by_id = actor_id
    _settle(invoice)
    await session.flush()


async def issue(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> None:
    found = await _locked(session, organization_id, invoice_id)
    invoice = found.invoice
    if invoice.status == billing.VOID:
        raise Voided
    if invoice.status != billing.DRAFT:
        raise Locked(f"This bill was issued already, as {invoice.invoice_number}.")
    await _issue(session, organization_id, clinic, invoice, actor_id)


async def discard(
    session: AsyncSession, *, organization_id: uuid.UUID, invoice_id: uuid.UUID
) -> None:
    """A draft goes without trace, since it never had a number or took money."""
    found = await _locked(session, organization_id, invoice_id)
    invoice = found.invoice
    if invoice.status != billing.DRAFT:
        raise Locked("An issued bill is kept. Void it instead.")
    await session.delete(invoice)
    await session.flush()


# --- Money -------------------------------------------------------------------------


async def pay(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    actor_id: uuid.UUID,
    may_issue: bool,
    invoice_id: uuid.UUID,
    body: PaymentIn,
    key: str | None,
) -> None:
    found = await _locked(session, organization_id, invoice_id)
    invoice = found.invoice
    payments = PaymentRepository(session, organization_id)
    # Looked for after the lock, so a retry arriving on the heels of the
    # first waits for it and then finds what it took.
    if key is not None and await payments.by_request(key) is not None:
        return

    if invoice.status == billing.VOID:
        raise Voided
    if invoice.refunded_amount > 0:
        raise Refunded
    if invoice.status == billing.DRAFT:
        # Taking the money is the moment the bill is handed over.
        if not may_issue:
            raise PermissionDenied("This bill is still a draft. Ask the desk to issue it.")
        await _issue(session, organization_id, clinic, invoice, actor_id)
    if invoice.balance <= 0:
        raise AlreadyPaid
    amount = body.amount.quantize(CENT)
    if amount > invoice.balance:
        error = _invalid(
            "amount",
            f"{rupees(invoice.balance)} is all that is owed on this bill.",
            code="BILLING_PAYMENT_EXCEEDS_BALANCE",
        )
        raise error

    payment = Payment(
        invoice_id=invoice.id,
        kind=billing.PAYMENT,
        amount=amount,
        method=body.method,
        reference=_blank(body.reference),
        note=_blank(body.note),
        received_at=dt.datetime.now(dt.UTC),
        received_by_id=actor_id,
        request_key=key,
    )
    try:
        async with session.begin_nested():
            await payments.add(payment)
    except IntegrityError:
        if key is not None and await payments.by_request(key) is not None:
            return
        raise
    invoice.amount_paid += amount
    _settle(invoice)
    await session.flush()


async def refund(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    role: str,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    body: RefundIn,
    key: str | None,
) -> None:
    if role != OWNER:
        raise PermissionDenied("Only the clinic admin can give money back.")
    found = await _locked(session, organization_id, invoice_id)
    invoice = found.invoice
    payments = PaymentRepository(session, organization_id)
    if key is not None and await payments.by_request(key) is not None:
        return
    if invoice.status == billing.VOID:
        raise Voided
    held = invoice.amount_paid - invoice.refunded_amount
    if held <= 0:
        raise _invalid(
            "amount",
            "Nothing has been taken on this bill to give back.",
            code="BILLING_REFUND_EXCEEDS_PAID",
        )
    amount = body.amount.quantize(CENT)
    if amount > held:
        raise _invalid(
            "amount",
            f"{rupees(held)} is all that has been taken on this bill.",
            code="BILLING_REFUND_EXCEEDS_PAID",
        )

    await payments.add(
        Payment(
            invoice_id=invoice.id,
            kind=billing.REFUND,
            amount=amount,
            method=body.method,
            reference=_blank(body.reference),
            note=body.reason,
            received_at=dt.datetime.now(dt.UTC),
            received_by_id=actor_id,
            request_key=key,
        )
    )
    invoice.refunded_amount += amount
    _settle(invoice)
    await session.flush()


def _why_not_voidable(invoice: Invoice) -> str | None:
    held = invoice.amount_paid - invoice.refunded_amount
    if held > 0:
        return (
            f"{rupees(held)} is still taken on this bill. "
            "It has to be given back before the bill can be voided."
        )
    return None


async def void(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    reason: str,
) -> None:
    found = await _locked(session, organization_id, invoice_id)
    invoice = found.invoice
    if invoice.status == billing.VOID:
        raise Voided("This bill has been voided already.")
    if invoice.status == billing.DRAFT:
        raise Locked("A draft has no number to void. Delete it instead.")
    why = _why_not_voidable(invoice)
    if why is not None:
        raise HasPayments(why)
    invoice.status = billing.VOID
    invoice.voided_at = dt.datetime.now(dt.UTC)
    invoice.voided_by_id = actor_id
    invoice.void_reason = reason
    await session.flush()


# --- What a bill starts from -------------------------------------------------------


async def _seen_lately(
    session: AsyncSession, organization_id: uuid.UUID, placed: Placed, window_days: int
) -> bool:
    """Whether this doctor saw the patient within the clinic's follow-up
    window, which is what makes a walk-in a follow-up."""
    if window_days <= 0:
        return False
    since = placed.entry.token_date - dt.timedelta(days=window_days)
    result = await session.execute(
        select(QueueEntry.id)
        .where(QueueEntry.organization_id == organization_id)
        .where(QueueEntry.patient_id == placed.patient.id)
        .where(QueueEntry.doctor_id == placed.doctor.id)
        .where(QueueEntry.status == queue.COMPLETED)
        .where(QueueEntry.id != placed.entry.id)
        .where(QueueEntry.token_date >= since)
        .where(QueueEntry.token_date < placed.entry.token_date)
        .limit(1)
    )
    return result.first() is not None


def _window(clinic: Organization) -> int:
    try:
        return int(clinic.effective_settings.get("follow_up_window_days") or 0)
    except (TypeError, ValueError):
        return 0


def _visit_ref(placed: Placed) -> dict[str, Any]:
    return {
        "queue_entry_id": placed.entry.id,
        "date": placed.entry.token_date,
        "token": placed.entry.token_number,
        "consultation_id": placed.consultation_id,
    }


async def starting(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    patient_id: uuid.UUID | None,
    queue_entry_id: uuid.UUID | None,
) -> dict[str, Any]:
    today = clinic_today(clinic)
    base = {
        "currency": clinic.currency,
        "tax_percent": _tax_percent(clinic),
        "lab_tests": [],
        "existing": None,
        "existing_number": None,
    }
    if queue_entry_id is None:
        if patient_id is None:
            raise ValidationFailed({"patient_id": "Say whose bill it is."})
        patient = await _patient(session, organization_id, patient_id)
        return {
            **base,
            "patient": patient_ref(patient, await _allergies(session, patient.id), today),
            "doctor": None,
            "visit": None,
            "items": [],
        }

    placed = await QueueRepository(session, organization_id).one(queue_entry_id)
    if placed is None:
        raise NotFound("That visit could not be found.")
    existing = await InvoiceRepository(session, organization_id).live_for_visit(placed.entry.id)

    doctor = placed.doctor
    appointment: Appointment | None = placed.appointment
    follow_up = (
        appointment.appointment_type == FOLLOW_UP
        if appointment is not None
        else await _seen_lately(session, organization_id, placed, _window(clinic))
    )
    if follow_up:
        fee, _ = effective_fee(doctor.follow_up_fee, clinic, "follow_up_fee")
        words = f"Follow-up consultation, {doctor.display_name}"
    else:
        fee, _ = effective_fee(doctor.consultation_fee, clinic, "consultation_fee")
        words = f"Consultation, {doctor.display_name}"

    tests: list[str] = []
    if placed.consultation_id is not None:
        result = await session.execute(
            select(LabOrder.test_name)
            .where(LabOrder.organization_id == organization_id)
            .where(LabOrder.consultation_id == placed.consultation_id)
            .where(LabOrder.status != lab.CANCELLED)
            .order_by(LabOrder.ordered_at)
        )
        tests = [row[0] for row in result.all()]

    return {
        **base,
        "patient": patient_ref(placed.patient, placed.allergy_count, today),
        "doctor": doctor_ref(doctor),
        "visit": _visit_ref(placed),
        "items": [
            {
                "item_type": "consultation",
                "description": words[:120],
                "quantity": 1,
                "unit_price": Decimal(fee),
            }
        ],
        "lab_tests": tests,
        "existing": existing.id if existing else None,
        "existing_number": existing.invoice_number if existing else None,
    }


async def _allergies(session: AsyncSession, patient_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(PatientAllergy)
        .where(PatientAllergy.patient_id == patient_id)
    )
    return int(result.scalar_one())


async def past_lines(
    session: AsyncSession, *, organization_id: uuid.UUID, typed: str | None, limit: int
) -> list[dict[str, Any]]:
    found = await InvoiceRepository(session, organization_id).past_lines(typed, limit=limit)
    return [
        {"description": words, "item_type": kind, "unit_price": price, "times": times}
        for words, kind, price, times in found
    ]


# --- Reading -------------------------------------------------------------------------


def _headline(found: Billed) -> str:
    if not found.items:
        return ""
    first = found.items[0].description
    more = len(found.items) - 1
    return f"{first} and {more} more" if more else first


def _totals(invoice: Invoice) -> dict[str, Any]:
    return {
        "subtotal": invoice.subtotal,
        "discount_amount": invoice.discount_amount,
        "tax_percent": invoice.tax_percent,
        "tax_amount": invoice.tax_amount,
        "total": invoice.total,
        "amount_paid": invoice.amount_paid,
        "refunded_amount": invoice.refunded_amount,
        "balance": invoice.balance,
    }


def _listed(found: Billed, today: dt.date) -> dict[str, Any]:
    invoice = found.invoice
    return {
        **_totals(invoice),
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "status": invoice.status,
        "patient": patient_ref(found.patient, found.allergy_count, today),
        "doctor": doctor_ref(found.doctor) if found.doctor else None,
        "headline": _headline(found),
        "lines": len(found.items),
        "created_at": invoice.created_at,
        "issued_at": invoice.issued_at,
    }


async def _names(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {each for each in ids if each is not None}
    if not wanted:
        return {}
    result = await session.execute(select(User).where(User.id.in_(wanted)))
    return {user.id: user.full_name for user in result.scalars().all()}


async def detail(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    permissions: frozenset[str],
    role: str,
    invoice_id: uuid.UUID,
) -> dict[str, Any]:
    found = await InvoiceRepository(session, organization_id).one(invoice_id)
    if found is None:
        raise InvoiceNotFound
    invoice = found.invoice
    today = clinic_today(clinic)
    payments = await PaymentRepository(session, organization_id).for_invoice(invoice.id)
    names = await _names(
        session, {invoice.created_by_id, invoice.issued_by_id, invoice.voided_by_id}
    )

    visit = None
    if invoice.queue_entry_id is not None:
        placed = await QueueRepository(session, organization_id).one(invoice.queue_entry_id)
        if placed is not None:
            visit = _visit_ref(placed)

    status = invoice.status
    held = invoice.amount_paid - invoice.refunded_amount
    issued = status not in (billing.DRAFT, billing.VOID)
    may_issue = "billing:create" in permissions
    can_void = "billing:update" in permissions and issued and held == 0

    return {
        **_listed(found, today),
        "currency": clinic.currency,
        "items": [
            {
                "item_type": item.item_type,
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "amount": item.amount,
            }
            for item in found.items
        ],
        "payments": [
            {
                "id": payment.id,
                "kind": payment.kind,
                "amount": payment.amount,
                "method": payment.method,
                "reference": payment.reference,
                "note": payment.note,
                "received_at": payment.received_at,
                "received_by": by,
            }
            for payment, by in payments
        ],
        "discount_reason": invoice.discount_reason,
        "notes": invoice.notes,
        "visit": visit,
        "created_by": names.get(invoice.created_by_id) if invoice.created_by_id else None,
        "issued_by": names.get(invoice.issued_by_id) if invoice.issued_by_id else None,
        "voided_at": invoice.voided_at,
        "voided_by": names.get(invoice.voided_by_id) if invoice.voided_by_id else None,
        "void_reason": invoice.void_reason,
        "can_edit": may_issue and status == billing.DRAFT,
        "can_pay": "payment:record" in permissions
        and invoice.refunded_amount == 0
        and invoice.balance > 0
        and (status in billing.OWED or (status == billing.DRAFT and may_issue)),
        "can_refund": role == OWNER and "payment:record" in permissions and issued and held > 0,
        "can_void": can_void,
        "void_blocked": _why_not_voidable(invoice)
        if "billing:update" in permissions and issued
        else None,
    }


SHOW: dict[str, tuple[str, ...] | None] = {
    "to_collect": billing.OWED,
    "drafts": (billing.DRAFT,),
    "paid": (billing.PAID, billing.REFUNDED),
    "void": (billing.VOID,),
    "all": None,
}


def _day_bounds(clinic: Organization, day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    zone = clinic_zone(clinic)
    since = dt.datetime.combine(day, dt.time(), tzinfo=zone)
    return since, since + dt.timedelta(days=1)


async def listed(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    show: str,
    patient_id: uuid.UUID | None,
    typed: str | None,
    since: dt.date | None,
    until: dt.date | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    if since is not None and until is not None and until < since:
        raise ValidationFailed({"to": "The end is before the start."})
    repository = InvoiceRepository(session, organization_id)
    found, total = await repository.listed(
        statuses=SHOW[show],
        patient_id=patient_id,
        typed=typed,
        since=_day_bounds(clinic, since)[0] if since else None,
        until=_day_bounds(clinic, until)[1] if until else None,
        limit=limit,
        offset=offset,
    )
    today = clinic_today(clinic)
    _, owed = await repository.outstanding(patient_id=patient_id)
    return {
        "items": [_listed(each, today) for each in found],
        "total": total,
        "counts": await repository.counts(patient_id=patient_id),
        "owed": owed,
    }


async def summary(
    session: AsyncSession, *, organization_id: uuid.UUID, clinic: Organization, day: dt.date
) -> dict[str, Any]:
    since, until = _day_bounds(clinic, day)
    rows = await PaymentRepository(session, organization_id).by_method(since, until)
    methods: dict[str, dict[str, Any]] = {}
    for method, kind, amount, count in rows:
        entry = methods.setdefault(
            method,
            {"method": method, "received": ZERO, "refunded": ZERO, "net": ZERO, "count": 0},
        )
        if kind == billing.REFUND:
            entry["refunded"] += amount
        else:
            entry["received"] += amount
            entry["count"] += count
        entry["net"] = entry["received"] - entry["refunded"]
    ordered = [methods[method] for method in billing.METHODS if method in methods]

    repository = InvoiceRepository(session, organization_id)
    issued_count, billed = await repository.issued_between(since, until)
    owed_count, owed = await repository.outstanding()
    received = sum((each["received"] for each in ordered), ZERO)
    refunded = sum((each["refunded"] for each in ordered), ZERO)
    return {
        "date": day,
        "currency": clinic.currency,
        "methods": ordered,
        "received": received,
        "refunded": refunded,
        "net": received - refunded,
        "bills_issued": issued_count,
        "billed": billed,
        "outstanding": owed,
        "outstanding_bills": owed_count,
    }


async def unbilled(
    session: AsyncSession, *, organization_id: uuid.UUID, clinic: Organization, day: dt.date
) -> dict[str, Any]:
    """Patients seen that day with no bill yet, most recently finished first."""
    placed = [
        each
        for each in await QueueRepository(session, organization_id).on_day(day)
        if each.entry.status == queue.COMPLETED
    ]
    billed = await InvoiceRepository(session, organization_id).billed_entries(
        [each.entry.id for each in placed]
    )
    left = [each for each in placed if each.entry.id not in billed]
    left.sort(
        key=lambda each: each.entry.completed_at or each.entry.checked_in_at, reverse=True
    )
    today = clinic_today(clinic)
    return {
        "date": day,
        "items": [
            {
                "queue_entry_id": each.entry.id,
                "token": each.entry.token_number,
                "status": each.entry.status,
                "patient": patient_ref(each.patient, each.allergy_count, today),
                "doctor": doctor_ref(each.doctor),
                "completed_at": each.entry.completed_at,
            }
            for each in left
        ],
    }
