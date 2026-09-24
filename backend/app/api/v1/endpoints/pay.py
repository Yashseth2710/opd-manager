"""Paying a bill without signing in.

Everything here is open on purpose: the patient has no account and never will.
What stands in for one is the link itself, which is an unguessable token that
only reaches the bill it was raised for, only while it is open, and only ever
shows what somebody being asked to pay has to be told.

The webhook is open for a different reason — Razorpay calls it, not a person —
and is admitted only if it carries their signature over the bytes they sent.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Path, Request

from app.api.deps import DbSession, client_ip
from app.core import rate_limit
from app.schemas.billing import CheckoutIn, PayView
from app.services import payment_links

router = APIRouter(tags=["payments"])

# Long enough for the token, short enough that nothing silly is looked up.
Token = Path(min_length=16, max_length=128)


@router.get("/pay/{token}")
async def open_bill(request: Request, session: DbSession, token: str = Token) -> PayView:
    """The bill behind a link: the clinic, what is owed, and whether it is
    still open. No address, no phone number, nothing clinical."""
    await rate_limit.check("pay", client_ip(request), rate_limit.PAY_PER_IP)
    found = await payment_links.view(session, token=token)
    return PayView.model_validate(found)


@router.post("/pay/{token}/confirm")
async def confirm_payment(
    request: Request, session: DbSession, body: CheckoutIn, token: str = Token
) -> PayView:
    """The checkout reporting back that it went through.

    Razorpay's webhook says the same thing independently, so a patient who
    closes the tab here is still marked paid. Whichever arrives first records
    the money and the other finds it recorded.
    """
    await rate_limit.check("pay", client_ip(request), rate_limit.PAY_PER_IP)
    found = await payment_links.confirm(
        session,
        token=token,
        order_id=body.razorpay_order_id,
        payment_id=body.razorpay_payment_id,
        signature=body.razorpay_signature,
    )
    return PayView.model_validate(found)


@router.post("/pay/webhook/razorpay")
async def razorpay_webhook(
    request: Request,
    session: DbSession,
    signature: str = Header(default="", alias="X-Razorpay-Signature"),
) -> dict[str, str]:
    """Razorpay's own report of a payment, signed over the exact bytes it
    sent — which is why the raw body is read rather than a parsed one."""
    handled = await payment_links.from_webhook(
        session, body=await request.body(), signature=signature
    )
    return {"status": handled}
