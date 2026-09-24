"""Paying a bill from a link, instead of at the desk.

The desk raises a link against what is still owed and either reads the address
out to the patient or has it emailed. The patient opens it on their phone,
pays by UPI or card, and the bill marks itself paid.

Two things report the payment and neither is trusted on its own. The patient's
browser comes back from the checkout with a signed handshake, which is quick
but only as reliable as their connection; Razorpay also calls the webhook,
which is slower but arrives whatever the patient's phone does. Both ask the
gateway what actually happened before a rupee is written down, and both take
the same path, so whichever gets there first records the money and the other
finds it already recorded.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import email as mail
from app.core import razorpay
from app.core.config import get_settings
from app.core.exceptions import AppError, NotFound, ValidationFailed
from app.core.security import hash_token, new_opaque_token
from app.models import Invoice, Organization, Payment, PaymentLink, User, billing
from app.models import notification as kinds
from app.repositories.billing import (
    Billed,
    InvoiceRepository,
    PaymentLinkRepository,
    PaymentRepository,
    link_by_order,
    link_by_token,
)
from app.services import events
from app.services.billing import ZERO, InvoiceNotFound, link_ref, link_status, rupees
from app.services.doctors import clinic_zone

logger = logging.getLogger("opd.payments")

# Razorpay signs the handshake and the webhook with a payment id of its own.
# Reusing it as the idempotency key is what makes the two reports of one
# payment collapse into a single row.
KEY_PREFIX = "rzp-"


class LinkNotFound(NotFound):
    code = "PAYMENT_LINK_NOT_FOUND"
    message = "That payment link is not valid. Ask the clinic for a new one."


class NothingOwed(AppError):
    code = "PAYMENT_LINK_NOTHING_OWED"
    status = 409
    message = "Nothing is owed on this bill, so there is nothing to send."


class LinkClosed(AppError):
    code = "PAYMENT_LINK_CLOSED"
    status = 409
    message = "This link is no longer open."


class CheckoutRejected(AppError):
    code = "PAYMENT_CHECKOUT_REJECTED"
    status = 400
    message = "That payment could not be confirmed. Nothing has been charged twice."


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _expiry() -> dt.datetime:
    return _now() + dt.timedelta(hours=get_settings().payment_link_hours)


def address(url: str, token: str) -> str:
    return f"{url.rstrip('/')}/pay/{token}"


# --- Raising one ---------------------------------------------------------------------


async def _billed(
    session: AsyncSession, organization_id: uuid.UUID, invoice_id: uuid.UUID, *, lock: bool
) -> Billed:
    found = await InvoiceRepository(session, organization_id).one(invoice_id, lock=lock)
    if found is None:
        raise InvoiceNotFound
    return found


def _why_not(invoice: Invoice) -> str | None:
    """Why this bill cannot be sent out to be paid, if it cannot."""
    if invoice.status == billing.DRAFT:
        return "This bill is still a draft. Issue it before sending it to be paid."
    if invoice.status == billing.VOID:
        return "This bill has been voided, so there is nothing to pay."
    if invoice.refunded_amount > 0:
        return "Money has been given back on this bill, so it takes no more payments."
    return None


async def raise_link(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    send_it: bool,
    to: str | None,
) -> dict[str, Any]:
    """A fresh link for what is still owed, and any live one called off.

    A new one each time is deliberate. Only the hash of a link is kept, so
    there is nothing to show twice, and one live link per bill means there is
    never a second address in circulation that would also take money.
    """
    if not razorpay.configured():
        raise razorpay.NotConfigured

    found = await _billed(session, organization_id, invoice_id, lock=True)
    invoice = found.invoice
    refused = _why_not(invoice)
    if refused is not None:
        raise LinkClosed(refused)
    if invoice.balance <= 0:
        raise NothingOwed

    where = (to or found.patient.email or "").strip()
    if send_it and not where:
        raise ValidationFailed(
            {"email": "This patient has no email address. Add one, or copy the link instead."}
        )

    links = PaymentLinkRepository(session, organization_id)
    live = await links.open_for_invoice(invoice.id)
    if live is not None:
        live.status = billing.LINK_CANCELLED
        await session.flush()

    order = await razorpay.open_order(
        amount=invoice.balance,
        currency=clinic.currency,
        receipt=str(invoice.id),
        notes={
            "bill": invoice.invoice_number or "",
            "clinic": clinic.name[:60],
        },
    )

    raw, hashed = new_opaque_token()
    link = PaymentLink(
        invoice_id=invoice.id,
        token_hash=hashed,
        provider="razorpay",
        order_id=order.id,
        amount=invoice.balance,
        excess_amount=ZERO,
        currency=clinic.currency,
        status=billing.LINK_OPEN,
        expires_at=_expiry(),
        created_by_id=actor_id,
    )
    await links.add(link)

    url = address(get_settings().app_url, raw)
    sent = False
    if send_it:
        sent = await _email(link, clinic, found, url, where)
        link.sent_to = where
        link.sent_at = _now() if sent else None
    await session.flush()

    name = await _actor_name(session, actor_id)
    return {**link_ref(link, name), "url": url, "sent": sent}


def when_words(moment: dt.datetime) -> str:
    """ "14 October, 6:30 pm". Written out rather than left to strftime,
    whose no-padding flags differ between platforms."""
    hour = moment.hour % 12 or 12
    half = "am" if moment.hour < 12 else "pm"
    return f"{moment.day} {moment.strftime('%B')}, {hour}:{moment.minute:02d} {half}"


async def _email(
    link: PaymentLink, clinic: Organization, found: Billed, url: str, to: str
) -> bool:
    message = mail.payment_link_message(
        to=to,
        name=found.patient.first_name,
        clinic=clinic.name,
        amount=rupees(link.amount),
        number=found.invoice.invoice_number or "",
        until=when_words(link.expires_at.astimezone(clinic_zone(clinic))),
        url=url,
    )
    delivery = await mail.send(message)
    return delivery.sent


async def _actor_name(session: AsyncSession, actor_id: uuid.UUID | None) -> str | None:
    if actor_id is None:
        return None
    user = await session.get(User, actor_id)
    return user.full_name if user else None


async def cancel_link(
    session: AsyncSession, *, organization_id: uuid.UUID, invoice_id: uuid.UUID
) -> None:
    """Takes the live link out of circulation. What was paid through an
    earlier one stays exactly where it is."""
    # Looked up first so another clinic's bill reads as absent rather than as
    # one of ours with no link on it.
    await _billed(session, organization_id, invoice_id, lock=False)
    links = PaymentLinkRepository(session, organization_id)
    live = await links.open_for_invoice(invoice_id)
    if live is None:
        raise LinkClosed("There is no link open on this bill.")
    live.status = billing.LINK_CANCELLED
    await session.flush()


# --- What the patient sees -----------------------------------------------------------


async def _found(session: AsyncSession, token: str) -> tuple[PaymentLink, Billed, Organization]:
    link = await link_by_token(session, hash_token(token))
    if link is None:
        raise LinkNotFound
    clinic = await session.get(Organization, link.organization_id)
    if clinic is None:
        raise LinkNotFound
    found = await _billed(session, link.organization_id, link.invoice_id, lock=False)
    return link, found, clinic


async def view(session: AsyncSession, *, token: str) -> dict[str, Any]:
    """The bill as the person holding the link sees it.

    Opening it is recorded once, so the desk can tell a link that was never
    looked at from one that was looked at and not paid.
    """
    link, found, clinic = await _found(session, token)
    invoice = found.invoice

    status = link_status(link)
    if status == billing.LINK_EXPIRED and link.status == billing.LINK_OPEN:
        link.status = billing.LINK_EXPIRED
    if status == billing.LINK_OPEN and link.opened_at is None:
        link.opened_at = _now()
    # A bill settled at the desk closes the link rather than leaving it
    # collecting money nobody owes.
    if status == billing.LINK_OPEN and invoice.balance <= 0:
        link.status = billing.LINK_CANCELLED
        status = billing.LINK_CANCELLED
    await session.flush()

    live = status == billing.LINK_OPEN
    return {
        "clinic": clinic.name,
        "clinic_phone": clinic.phone,
        "patient_name": found.patient.full_name,
        "invoice_number": invoice.invoice_number,
        "issued_on": invoice.issued_at.astimezone(clinic_zone(clinic)).date()
        if invoice.issued_at
        else None,
        "amount": link.amount,
        "currency": link.currency,
        "status": status,
        "expires_at": link.expires_at,
        "paid_at": link.paid_at,
        "key_id": razorpay.public_key() if live and razorpay.configured() else None,
        "order_id": link.order_id if live else None,
    }


async def confirm(
    session: AsyncSession, *, token: str, order_id: str, payment_id: str, signature: str
) -> dict[str, Any]:
    """The patient's browser reporting that the checkout went through.

    The signature proves the report came from the checkout rather than from
    somebody typing into the address bar. It still settles nothing by itself:
    what the gateway says about the payment is what gets written down.
    """
    link, _, _ = await _found(session, token)
    if link.order_id != order_id:
        raise CheckoutRejected
    if not razorpay.checkout_signature_ok(
        order_id=order_id, payment_id=payment_id, signature=signature
    ):
        logger.warning("checkout handshake did not verify for order %s", order_id)
        raise CheckoutRejected

    await settle(session, link=link, payment_id=payment_id)
    return await view(session, token=token)


# --- Recording the money -------------------------------------------------------------


async def settle(session: AsyncSession, *, link: PaymentLink, payment_id: str) -> None:
    """Writes the payment, once, whichever side reported it.

    Everything here is decided from what the gateway says, and the invoice is
    locked first so a payment arriving twice — once from the browser, once
    from the webhook — cannot be counted twice.
    """
    if link.gateway_payment_id == payment_id:
        return

    gateway = await razorpay.read_payment(payment_id)
    if gateway.order_id != link.order_id:
        logger.warning(
            "payment %s belongs to order %s, not %s",
            payment_id,
            gateway.order_id,
            link.order_id,
        )
        raise CheckoutRejected

    if gateway.status == "authorized" and not gateway.captured:
        gateway = await razorpay.capture(
            payment_id, amount_paise=gateway.amount_paise, currency=link.currency
        )
    if gateway.status != "captured":
        # Failed, or still being decided. Nothing is written and the link
        # stays open so the patient can try again.
        logger.info("payment %s is %s, nothing recorded", payment_id, gateway.status)
        raise CheckoutRejected

    organization_id = link.organization_id
    found = await _billed(session, organization_id, link.invoice_id, lock=True)
    invoice = found.invoice
    payments = PaymentRepository(session, organization_id)
    key = f"{KEY_PREFIX}{payment_id}"
    if await payments.by_request(key) is not None:
        # Recorded already, by the other side or by an earlier link on this
        # same bill. Whatever it worked out as excess stands.
        _mark_paid(link, payment_id, link.excess_amount)
        await session.flush()
        return

    takeable = _takeable(invoice, gateway.amount)
    excess = gateway.amount - takeable
    written: Payment | None = None
    if takeable > 0:
        written = Payment(
            invoice_id=invoice.id,
            kind=billing.PAYMENT,
            amount=takeable,
            method=gateway.our_method,
            channel=billing.ONLINE,
            reference=payment_id,
            # No note: the channel says it came from a link and the reference
            # says which payment, so a sentence repeating that earns nothing.
            note=None,
            received_at=_now(),
            received_by_id=None,
            request_key=key,
        )
        try:
            async with session.begin_nested():
                await payments.add(written)
        except IntegrityError:
            # The other side got there first between the lock and the write.
            if await payments.by_request(key) is None:
                raise
            written = None
        else:
            invoice.amount_paid += takeable
            _resettle(invoice)

    if excess > 0:
        logger.warning(
            "payment %s is %s more than bill %s had owing",
            payment_id,
            excess,
            invoice.invoice_number,
        )
    _mark_paid(link, payment_id, excess)
    if written is not None:
        link.payment_id = written.id
    await session.flush()
    if written is not None or excess > 0:
        await _announce(
            session, invoice, takeable if written else ZERO, excess, gateway.our_method
        )


async def _announce(
    session: AsyncSession, invoice: Invoice, taken: Decimal, excess: Decimal, method: str
) -> None:
    """Into the log, and to everyone who reads bills: the desk will want to
    know the patient has paid, and above all when there is money to give back."""
    organization_id = invoice.organization_id
    patient = await events.patient_named(session, organization_id, invoice.patient_id)
    number = invoice.invoice_number or "a bill"
    await events.record(
        session,
        organization_id=organization_id,
        actor=events.PATIENT_ONLINE,
        action="payment.online",
        resource_type="invoice",
        resource_id=invoice.id,
        label=f"{number} for {patient}",
        changes={
            "amount": taken,
            "method": method,
            "balance": invoice.balance,
            "excess": excess or None,
        },
    )
    if excess > 0:
        title = f"{rupees(excess)} paid online on {number} with nothing owing"
        body = "The bill was settled before the payment arrived. Give the money back."
    else:
        title = f"{rupees(taken)} paid online on {number}"
        body = f"{patient}. " + (
            "Nothing more is owed."
            if invoice.balance <= 0
            else f"{rupees(invoice.balance)} still owed."
        )
    await events.tell(
        session,
        organization_id=organization_id,
        users=await events.holding(session, organization_id, "billing:read"),
        notice=events.Notice(
            kind=kinds.PAID_ONLINE, title=title, body=body, link=f"/billing/{invoice.id}"
        ),
        besides=None,
    )


def _takeable(invoice: Invoice, amount: Decimal) -> Decimal:
    """What of this payment the bill can still hold.

    A bill that was voided or settled at the desk while the patient was
    paying takes none of it; the money is real and is written down as excess
    for the desk to give back.
    """
    if invoice.status in (billing.VOID, billing.REFUNDED) or invoice.refunded_amount > 0:
        return ZERO
    return min(amount, invoice.balance) if invoice.balance > 0 else ZERO


def _resettle(invoice: Invoice) -> None:
    invoice.balance = invoice.total - invoice.amount_paid
    invoice.status = billing.PAID if invoice.balance == 0 else billing.PARTLY_PAID


def _mark_paid(link: PaymentLink, payment_id: str, excess: Decimal) -> None:
    link.gateway_payment_id = payment_id
    link.excess_amount = excess
    if link.status != billing.LINK_PAID:
        link.status = billing.LINK_PAID
        link.paid_at = _now()


# --- The webhook ---------------------------------------------------------------------

# The events worth acting on. Everything else Razorpay sends is acknowledged
# and dropped: answering anything but 200 makes them retry for hours over
# something that was never going to be handled.
HANDLED = ("payment.captured", "order.paid")


async def from_webhook(session: AsyncSession, *, body: bytes, signature: str) -> str:
    """Razorpay's own report that a payment went through.

    This is the reliable half. A patient who paid and then closed the tab, or
    lost signal on the way home, is still marked paid because of this.
    """
    if not razorpay.webhook_signature_ok(body, signature):
        logger.warning("webhook signature did not verify")
        raise CheckoutRejected("That webhook could not be verified.")

    payload = _parsed(body)
    event = str(payload.get("event") or "")
    if event not in HANDLED:
        return "ignored"

    # Both events we act on carry the payment under the same path. Walked
    # rather than indexed, because this body came from outside.
    entity = _inside(payload, "payload", "payment", "entity")
    payment_id = str(entity.get("id") or "")
    order_id = str(entity.get("order_id") or "")
    if not payment_id or not order_id:
        return "ignored"

    link = await link_by_order(session, order_id)
    if link is None:
        logger.warning("webhook names order %s, which is not one of ours", order_id)
        return "ignored"

    try:
        await settle(session, link=link, payment_id=payment_id)
    except CheckoutRejected:
        # Nothing to record yet. Razorpay retries, and the patient's own
        # browser may well have settled it in the meantime anyway.
        return "ignored"
    return "recorded"


def _inside(payload: dict[str, Any], *path: str) -> dict[str, Any]:
    """Follows a path through a body somebody else wrote, giving up quietly
    the moment it is not shaped the way it should be."""
    found: Any = payload
    for step in path:
        if not isinstance(found, dict):
            return {}
        found = found.get(step)
    return found if isinstance(found, dict) else {}


def _parsed(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise CheckoutRejected("That webhook could not be read.") from exc
    return payload if isinstance(payload, dict) else {}
