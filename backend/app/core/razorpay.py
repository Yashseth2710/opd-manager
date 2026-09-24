"""Razorpay, for a patient paying a bill from their own phone.

Only the four calls the application needs are here: open an order for what is
owed, read a payment back, capture one the patient authorised but that was
not taken, and check the two signatures Razorpay signs things with.

Nothing here decides anything about a bill. A payment is worth recording only
once this module has said the gateway agrees it happened, and that judgement
is made in the service above.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import AppError

logger = logging.getLogger("opd.razorpay")

# Long enough for a gateway in another region on a slow day, short enough
# that a hung call does not hold a serverless function open to its limit.
TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# What Razorpay calls the way money came, against what the bill calls it.
# Anything new they add lands on "other" rather than losing the payment.
METHODS = {
    "upi": "upi",
    "card": "card",
    "netbanking": "bank_transfer",
    "wallet": "other",
    "emi": "card",
    "paylater": "other",
}


class NotConfigured(AppError):
    code = "PAYMENTS_NOT_CONFIGURED"
    status = 503
    message = "Online payment is not set up for this clinic yet."


class GatewayFailed(AppError):
    code = "PAYMENTS_GATEWAY_FAILED"
    status = 502
    message = "The payment service did not answer. Try again in a moment."


@dataclass(frozen=True)
class Order:
    id: str
    amount_paise: int
    status: str


@dataclass(frozen=True)
class GatewayPayment:
    """A payment as Razorpay has it, which is the only version that counts."""

    id: str
    order_id: str | None
    status: str
    amount_paise: int
    method: str
    captured: bool

    @property
    def our_method(self) -> str:
        return METHODS.get(self.method, "other")

    @property
    def amount(self) -> Decimal:
        return (Decimal(self.amount_paise) / 100).quantize(Decimal("0.01"))


def configured() -> bool:
    return get_settings().online_payments


def public_key() -> str:
    """The half of the pair the checkout script on the page needs. It is
    meant to be seen; the secret never leaves the server."""
    settings = get_settings()
    if not settings.online_payments:
        raise NotConfigured
    return settings.razorpay_key_id


def to_paise(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def _auth() -> tuple[str, str]:
    settings = get_settings()
    if not settings.online_payments:
        raise NotConfigured
    return settings.razorpay_key_id, settings.razorpay_key_secret


async def _call(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.request(
                method, f"{settings.razorpay_api_url}{path}", auth=_auth(), **kwargs
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        # Their message names the field they disliked and nothing private.
        logger.error("razorpay refused %s %s: %s", method, path, exc.response.text[:400])
        raise GatewayFailed from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("razorpay did not answer %s %s", method, path)
        raise GatewayFailed from exc
    if not isinstance(body, dict):
        raise GatewayFailed
    return body


async def open_order(
    *, amount: Decimal, currency: str, receipt: str, notes: dict[str, str]
) -> Order:
    """Tells Razorpay what is about to be paid, so the checkout can only take
    that amount and the webhook that follows can be tied back to the bill."""
    body = await _call(
        "POST",
        "/orders",
        json={
            "amount": to_paise(amount),
            "currency": currency,
            "receipt": receipt[:40],
            "notes": notes,
        },
    )
    return Order(
        id=str(body["id"]),
        amount_paise=int(body.get("amount") or 0),
        status=str(body.get("status") or ""),
    )


def _payment(body: dict[str, Any]) -> GatewayPayment:
    return GatewayPayment(
        id=str(body["id"]),
        order_id=str(body["order_id"]) if body.get("order_id") else None,
        status=str(body.get("status") or ""),
        amount_paise=int(body.get("amount") or 0),
        method=str(body.get("method") or ""),
        captured=bool(body.get("captured")),
    )


async def read_payment(payment_id: str) -> GatewayPayment:
    return _payment(await _call("GET", f"/payments/{payment_id}"))


async def capture(payment_id: str, *, amount_paise: int, currency: str) -> GatewayPayment:
    """Takes a payment the patient authorised but that was left held.

    Orders are opened for automatic capture, so this is the uncommon path: an
    account configured the other way, or a capture that failed on their side.
    Capturing one that is captured already answers with the payment, so a
    retry is safe.
    """
    return _payment(
        await _call(
            "POST",
            f"/payments/{payment_id}/capture",
            json={"amount": amount_paise, "currency": currency},
        )
    )


def _signed(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def checkout_signature_ok(*, order_id: str, payment_id: str, signature: str) -> bool:
    """What the checkout hands back to the page when a payment goes through.

    It is signed with the API secret, so a browser cannot forge one. It is
    still only the patient's word that it happened, which is why it is
    checked against the gateway before any money is recorded.
    """
    settings = get_settings()
    if not settings.online_payments or not signature:
        return False
    expected = _signed(f"{order_id}|{payment_id}", settings.razorpay_key_secret)
    return hmac.compare_digest(expected, signature)


def webhook_signature_ok(body: bytes, signature: str) -> bool:
    """Signed over the exact bytes Razorpay sent, which is why the handler
    reads the raw body and never a parsed and re-encoded version of it."""
    secret = get_settings().razorpay_webhook_secret
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
