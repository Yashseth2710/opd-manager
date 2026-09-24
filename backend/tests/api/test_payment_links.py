"""Paying a bill from a link, without an account.

The gateway is stood in for: what is worth testing here is what the
application decides when it is told a payment happened, not whether httpx can
reach Razorpay. The signatures are real, computed the way Razorpay computes
them, so a forged handshake is refused by the same code that refuses one in
production.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import razorpay
from app.core.config import get_settings
from app.main import app
from app.models import PaymentLink
from tests.api.test_billing import a_desk, one, paid, raised, summary, void
from tests.api.test_clinic import invite_and_accept
from tests.api.test_consultations import become
from tests.conftest import Outbox

API = "/api/v1"

KEY_ID = "rzp_test_suite"
KEY_SECRET = "suite-secret"  # pragma: allowlist secret
HOOK_SECRET = "suite-hook-secret"  # pragma: allowlist secret
# What somebody forging a report would be signing with: anything but the two
# above.
GUESSED = "not-the-one"  # pragma: allowlist secret


class FakeGateway:
    """Razorpay, as far as this application can tell.

    Payments are made here by the test rather than by a patient, which is
    exactly the position the application is in: it is told about a payment
    and has to decide what that means for the bill.
    """

    def __init__(self) -> None:
        self.orders: dict[str, razorpay.Order] = {}
        self.payments: dict[str, razorpay.GatewayPayment] = {}
        self.captured: list[str] = []
        self.refuse = False

    async def open_order(
        self, *, amount: Decimal, currency: str, receipt: str, notes: dict[str, str]
    ) -> razorpay.Order:
        if self.refuse:
            raise razorpay.GatewayFailed
        order = razorpay.Order(
            id=f"order_{len(self.orders) + 1:04d}",
            amount_paise=razorpay.to_paise(amount),
            status="created",
        )
        self.orders[order.id] = order
        return order

    def pays(
        self,
        order_id: str,
        *,
        amount: str | None = None,
        status: str = "captured",
        method: str = "upi",
        captured: bool = True,
    ) -> razorpay.GatewayPayment:
        """The patient paying, from the gateway's side of the glass."""
        order = self.orders[order_id]
        payment = razorpay.GatewayPayment(
            id=f"pay_{len(self.payments) + 1:04d}",
            order_id=order_id,
            status=status,
            amount_paise=razorpay.to_paise(Decimal(amount)) if amount else order.amount_paise,
            method=method,
            captured=captured,
        )
        self.payments[payment.id] = payment
        return payment

    async def read_payment(self, payment_id: str) -> razorpay.GatewayPayment:
        if payment_id not in self.payments:
            raise razorpay.GatewayFailed
        return self.payments[payment_id]

    async def capture(
        self, payment_id: str, *, amount_paise: int, currency: str
    ) -> razorpay.GatewayPayment:
        self.captured.append(payment_id)
        held = self.payments[payment_id]
        taken = razorpay.GatewayPayment(
            id=held.id,
            order_id=held.order_id,
            status="captured",
            amount_paise=amount_paise,
            method=held.method,
            captured=True,
        )
        self.payments[payment_id] = taken
        return taken


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGateway]:
    settings = get_settings()
    monkeypatch.setattr(settings, "razorpay_key_id", KEY_ID)
    monkeypatch.setattr(settings, "razorpay_key_secret", KEY_SECRET)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", HOOK_SECRET)
    double = FakeGateway()
    monkeypatch.setattr(razorpay, "open_order", double.open_order)
    monkeypatch.setattr(razorpay, "read_payment", double.read_payment)
    monkeypatch.setattr(razorpay, "capture", double.capture)
    yield double


@pytest.fixture
def no_gateway(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    settings = get_settings()
    monkeypatch.setattr(settings, "razorpay_key_id", "")
    monkeypatch.setattr(settings, "razorpay_key_secret", "")
    yield


def handshake(
    order_id: str, payment: razorpay.GatewayPayment, secret: str = KEY_SECRET
) -> dict[str, str]:
    signed = hmac.new(
        secret.encode(), f"{order_id}|{payment.id}".encode(), hashlib.sha256
    ).hexdigest()
    return {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment.id,
        "razorpay_signature": signed,
    }


def token_from(url: str) -> str:
    return url.rsplit("/", 1)[1]


async def link_for(client: AsyncClient, bill: dict[str, Any], **body: Any) -> Response:
    return await client.post(
        f"{API}/invoices/{bill['id']}/payment-link", json={"send": False, **body}
    )


async def linked(client: AsyncClient, bill: dict[str, Any], **body: Any) -> dict[str, Any]:
    response = await link_for(client, bill, **body)
    assert response.status_code == 201, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


def a_stranger() -> AsyncClient:
    """A browser with no session at all, which is what the patient has.

    Deliberately not the signed-in client the rest of the suite uses: these
    routes have to work for somebody who has never had an account, and a
    cookie riding along would hide it if they quietly stopped.
    """
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")


async def opened_by_patient(_: AsyncClient, token: str) -> Response:
    async with a_stranger() as patient:
        return await patient.get(f"{API}/pay/{token}")


async def confirm(_: AsyncClient, token: str, body: dict[str, str]) -> Response:
    async with a_stranger() as patient:
        return await patient.post(f"{API}/pay/{token}/confirm", json=body)


def webhook_body(payment: razorpay.GatewayPayment, event: str = "payment.captured") -> bytes:
    return json.dumps(
        {
            "event": event,
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment.id,
                        "order_id": payment.order_id,
                        "status": payment.status,
                        "amount": payment.amount_paise,
                        "method": payment.method,
                    }
                }
            },
        }
    ).encode()


async def webhook(_: AsyncClient, body: bytes, *, secret: str = HOOK_SECRET) -> Response:
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    async with a_stranger() as gateway_caller:
        return await gateway_caller.post(
            f"{API}/pay/webhook/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
        )


async def a_bill(client: AsyncClient, outbox: Outbox, **overrides: Any) -> dict[str, Any]:
    """An issued bill for 150 with nothing paid on it."""
    _, patient = await a_desk(client, outbox)
    return await raised(client, patient, issue=True, **overrides)


class TestRaisingALink:
    async def test_a_link_is_raised_for_what_is_owed(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)

        made = await linked(client, bill)

        assert made["status"] == "open"
        assert made["amount"] == bill["balance"]
        assert made["url"].startswith("http")
        assert made["sent"] is False
        assert made["sent_to"] is None
        assert len(gateway.orders) == 1

    async def test_it_carries_the_bill_that_is_owed_not_the_whole_total(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        part = await paid(client, bill, "50.00")

        made = await linked(client, part)

        assert made["amount"] == "100.00"

    async def test_raising_a_second_one_retires_the_first(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        first = await linked(client, bill)

        second = await linked(client, bill)

        assert second["id"] != first["id"]
        stale = await opened_by_patient(client, token_from(first["url"]))
        assert stale.json()["data"]["status"] == "cancelled"
        live = await opened_by_patient(client, token_from(second["url"]))
        assert live.json()["data"]["status"] == "open"

    async def test_a_draft_has_nothing_to_send(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        _, patient = await a_desk(client, outbox)
        draft = await raised(client, patient)

        response = await link_for(client, draft)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PAYMENT_LINK_CLOSED"
        assert "draft" in response.json()["error"]["message"].lower()

    async def test_a_settled_bill_has_nothing_to_send(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        settled = await paid(client, bill, bill["balance"])

        response = await link_for(client, settled)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PAYMENT_LINK_NOTHING_OWED"

    async def test_a_voided_bill_has_nothing_to_send(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        await void(client, bill)

        response = await link_for(client, bill)

        assert response.status_code == 409

    async def test_a_bill_with_money_given_back_takes_no_more(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        part = await paid(client, bill, "50.00")
        await client.post(
            f"{API}/invoices/{part['id']}/refunds",
            json={"amount": "50.00", "method": "cash", "reason": "Charged twice"},
        )

        response = await link_for(client, bill)

        assert response.status_code == 409

    async def test_with_no_gateway_configured_the_option_is_refused(
        self, client: AsyncClient, outbox: Outbox, no_gateway: None
    ) -> None:
        bill = await a_bill(client, outbox)

        response = await link_for(client, bill)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "PAYMENTS_NOT_CONFIGURED"

    async def test_a_gateway_that_will_not_answer_leaves_no_link_behind(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway, session: AsyncSession
    ) -> None:
        bill = await a_bill(client, outbox)
        gateway.refuse = True

        response = await link_for(client, bill)

        assert response.status_code == 502
        rows = await session.execute(select(PaymentLink))
        assert rows.scalars().all() == []

    async def test_another_clinics_bill_is_simply_not_there(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        await a_desk(client, outbox)

        response = await link_for(client, bill)

        assert response.status_code == 404


class TestSendingIt:
    async def test_it_goes_to_the_patients_own_address(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        _, patient = await a_desk(client, outbox)
        await client.patch(
            f"{API}/patients/{patient['id']}", json={"email": "asha@example.org"}
        )
        bill = await raised(client, patient, issue=True)

        made = await linked(client, bill, send=True)

        assert made["sent"] is True
        assert made["sent_to"] == "asha@example.org"
        assert outbox.recipients[-1] == "asha@example.org"
        assert made["url"] in outbox.messages[-1].action_url

    async def test_the_message_says_what_is_owed(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        _, patient = await a_desk(client, outbox)
        await client.patch(
            f"{API}/patients/{patient['id']}", json={"email": "asha@example.org"}
        )
        bill = await raised(client, patient, issue=True)

        await linked(client, bill, send=True)

        message = outbox.messages[-1]
        assert "150.00" in message.subject
        assert bill["invoice_number"] in message.body

    async def test_somewhere_else_can_be_asked_for(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)

        made = await linked(client, bill, send=True, email="son@example.org")

        assert made["sent_to"] == "son@example.org"
        assert outbox.recipients[-1] == "son@example.org"

    async def test_a_patient_with_no_address_is_said_so_plainly(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)

        response = await link_for(client, bill, send=True)

        assert response.status_code == 422
        assert "email" in response.json()["error"]["fields"]


class TestOpeningIt:
    async def test_the_patient_sees_the_bill_without_signing_in(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)
        made = await linked(client, bill)

        response = await opened_by_patient(client, token_from(made["url"]))

        assert response.status_code == 200
        found = response.json()["data"]
        assert found["clinic"] == "Sunrise Family Clinic"
        assert found["patient_name"] == f"{patient['first_name']} {patient['last_name']}"
        assert found["invoice_number"] == bill["invoice_number"]
        assert found["amount"] == "150.00"
        assert found["status"] == "open"
        assert found["key_id"] == KEY_ID
        assert found["order_id"] in gateway.orders

    async def test_it_says_nothing_about_the_patient_it_does_not_have_to(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)

        found = (await opened_by_patient(client, token_from(made["url"]))).json()["data"]

        assert set(found) == {
            "clinic",
            "clinic_phone",
            "patient_name",
            "invoice_number",
            "issued_on",
            "amount",
            "currency",
            "status",
            "expires_at",
            "paid_at",
            "key_id",
            "order_id",
        }

    async def test_a_made_up_link_is_not_there(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        response = await opened_by_patient(client, "a" * 40)

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PAYMENT_LINK_NOT_FOUND"

    async def test_the_desk_can_tell_it_was_opened(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        assert made["opened_at"] is None

        await opened_by_patient(client, token_from(made["url"]))

        assert (await one(client, bill["id"]))["payment_link"]["opened_at"] is not None

    async def test_an_old_link_has_gone_stale(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway, session: AsyncSession
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        await session.execute(
            update(PaymentLink).values(
                expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
            )
        )
        await session.commit()

        found = (await opened_by_patient(client, token_from(made["url"]))).json()["data"]

        assert found["status"] == "expired"
        assert found["order_id"] is None
        assert found["key_id"] is None

    async def test_a_bill_settled_at_the_desk_closes_the_link(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        await paid(client, bill, bill["balance"])

        found = (await opened_by_patient(client, token_from(made["url"]))).json()["data"]

        assert found["status"] == "cancelled"
        assert found["order_id"] is None


class TestPayingIt:
    async def test_a_confirmed_payment_settles_the_bill(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        payment = gateway.pays(order)

        response = await confirm(client, token, handshake(order, payment))

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "paid"
        settled = await one(client, bill["id"])
        assert settled["status"] == "paid"
        assert settled["balance"] == "0.00"
        assert len(settled["payments"]) == 1
        assert settled["payments"][0]["channel"] == "online"
        assert settled["payments"][0]["method"] == "upi"
        assert settled["payments"][0]["reference"] == payment.id
        assert settled["payment_link"]["status"] == "paid"

    async def test_how_the_money_came_is_carried_over(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        payment = gateway.pays(order, method="netbanking")

        await confirm(client, token, handshake(order, payment))

        settled = await one(client, bill["id"])
        assert settled["payments"][0]["method"] == "bank_transfer"

    async def test_confirming_twice_takes_the_money_once(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        payment = gateway.pays(order)
        told = handshake(order, payment)

        await confirm(client, token, told)
        second = await confirm(client, token, told)

        assert second.status_code == 200
        settled = await one(client, bill["id"])
        assert len(settled["payments"]) == 1
        assert settled["amount_paid"] == "150.00"

    async def test_a_forged_handshake_is_refused(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        payment = gateway.pays(order)

        response = await confirm(client, token, handshake(order, payment, secret=GUESSED))

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "PAYMENT_CHECKOUT_REJECTED"
        assert (await one(client, bill["id"]))["payments"] == []

    async def test_a_handshake_for_somebody_elses_order_is_refused(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        other = await gateway.open_order(
            amount=Decimal("150.00"), currency="INR", receipt="someone-else", notes={}
        )
        payment = gateway.pays(other.id)

        response = await confirm(client, token, handshake(other.id, payment))

        assert response.status_code == 400
        assert (await one(client, bill["id"]))["payments"] == []

    async def test_a_payment_that_did_not_go_through_records_nothing(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        payment = gateway.pays(order, status="failed", captured=False)

        response = await confirm(client, token, handshake(order, payment))

        assert response.status_code == 400
        assert (await one(client, bill["id"]))["payments"] == []
        found = (await opened_by_patient(client, token)).json()["data"]
        assert found["status"] == "open"

    async def test_money_held_but_not_taken_is_taken(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        payment = gateway.pays(order, status="authorized", captured=False)

        response = await confirm(client, token, handshake(order, payment))

        assert response.status_code == 200
        assert gateway.captured == [payment.id]
        assert (await one(client, bill["id"]))["status"] == "paid"

    async def test_money_the_bill_no_longer_needs_is_written_down(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        await paid(client, bill, "100.00")
        payment = gateway.pays(order)

        await confirm(client, token, handshake(order, payment))

        settled = await one(client, bill["id"])
        assert settled["status"] == "paid"
        assert settled["amount_paid"] == "150.00"
        assert settled["payment_link"]["excess_amount"] == "100.00"

    async def test_a_bill_voided_mid_payment_keeps_the_money_visible(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        await void(client, bill)
        payment = gateway.pays(order)

        await confirm(client, token, handshake(order, payment))

        settled = await one(client, bill["id"])
        assert settled["status"] == "void"
        assert settled["payments"] == []
        assert settled["payment_link"]["excess_amount"] == "150.00"


class TestTheWebhook:
    async def test_it_records_the_payment_on_its_own(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        order = (await opened_by_patient(client, token_from(made["url"]))).json()["data"][
            "order_id"
        ]
        payment = gateway.pays(order)

        response = await webhook(client, webhook_body(payment))

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "recorded"
        settled = await one(client, bill["id"])
        assert settled["status"] == "paid"
        assert settled["payments"][0]["channel"] == "online"

    async def test_one_that_is_not_signed_is_refused(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        order = (await opened_by_patient(client, token_from(made["url"]))).json()["data"][
            "order_id"
        ]
        payment = gateway.pays(order)

        response = await webhook(client, webhook_body(payment), secret=GUESSED)

        assert response.status_code == 400
        assert (await one(client, bill["id"]))["payments"] == []

    async def test_the_signature_is_over_the_bytes_that_were_sent(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        order = (await opened_by_patient(client, token_from(made["url"]))).json()["data"][
            "order_id"
        ]
        payment = gateway.pays(order)
        body = webhook_body(payment)
        signature = hmac.new(HOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

        # The same payload, re-encoded. A verifier that parsed first and
        # signed the result would wave this through.
        tampered = json.dumps(json.loads(body), indent=2).encode()
        async with a_stranger() as caller:
            response = await caller.post(
                f"{API}/pay/webhook/razorpay",
                content=tampered,
                headers={"X-Razorpay-Signature": signature},
            )

        assert response.status_code == 400

    async def test_a_webhook_after_the_browser_takes_nothing_twice(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        payment = gateway.pays(order)
        await confirm(client, token, handshake(order, payment))

        response = await webhook(client, webhook_body(payment))

        assert response.status_code == 200
        settled = await one(client, bill["id"])
        assert len(settled["payments"]) == 1
        assert settled["amount_paid"] == "150.00"

    async def test_an_order_that_is_not_ours_is_let_go(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        stranger = razorpay.GatewayPayment(
            id="pay_stranger",
            order_id="order_stranger",
            status="captured",
            amount_paise=10000,
            method="card",
            captured=True,
        )

        response = await webhook(client, webhook_body(stranger))

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "ignored"

    async def test_an_event_we_do_not_act_on_is_let_go(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        order = (await opened_by_patient(client, token_from(made["url"]))).json()["data"][
            "order_id"
        ]
        payment = gateway.pays(order)

        response = await webhook(client, webhook_body(payment, event="payment.failed"))

        assert response.json()["data"]["status"] == "ignored"
        assert (await one(client, bill["id"]))["payments"] == []


class TestWhatTheDeskSees:
    async def test_the_bill_carries_the_link_and_what_became_of_it(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        assert (await one(client, bill["id"]))["payment_link"] is None

        await linked(client, bill)

        found = await one(client, bill["id"])
        assert found["payment_link"]["status"] == "open"
        assert found["can_send_link"] is True
        assert found["online_payments"] is True

    async def test_the_option_is_absent_when_there_is_no_gateway(
        self, client: AsyncClient, outbox: Outbox, no_gateway: None
    ) -> None:
        bill = await a_bill(client, outbox)

        found = await one(client, bill["id"])

        assert found["online_payments"] is False
        assert found["can_send_link"] is False

    async def test_a_link_can_be_called_off(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)

        response = await client.delete(f"{API}/invoices/{bill['id']}/payment-link")

        assert response.status_code == 200
        assert response.json()["data"]["payment_link"]["status"] == "cancelled"
        found = (await opened_by_patient(client, token_from(made["url"]))).json()["data"]
        assert found["status"] == "cancelled"
        assert found["order_id"] is None

    async def test_calling_off_nothing_says_so(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)

        response = await client.delete(f"{API}/invoices/{bill['id']}/payment-link")

        assert response.status_code == 409

    async def test_the_days_takings_separate_what_nobody_handled(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        made = await linked(client, bill)
        token = token_from(made["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        await confirm(client, token, handshake(order, gateway.pays(order)))

        counted = await summary(client)

        assert counted["received"] == "150.00"
        assert counted["online"] == "150.00"

    async def test_money_taken_at_the_desk_is_not_counted_as_online(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        bill = await a_bill(client, outbox)
        await paid(client, bill, "150.00")

        counted = await summary(client)

        assert counted["received"] == "150.00"
        assert counted["online"] == "0.00"


class TestWhoMaySendOne:
    async def test_somebody_who_only_reads_bills_cannot_send_one(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)
        address = await invite_and_accept(client, role="staff", outbox=outbox)
        await become(client, address)

        response = await link_for(client, bill)

        assert response.status_code == 403
