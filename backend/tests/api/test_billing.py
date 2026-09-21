"""Bills: raised at the desk, usually for a visit, paid in one go or in parts,
and put right by a refund or a void rather than an edit."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import QueueEntry
from app.services.billing import financial_year, rupees
from tests.api.test_appointments import doctor_with_hours
from tests.api.test_clinic import invite_and_accept, sign_up
from tests.api.test_consultations import Clinic, a_clinic, become, opened
from tests.api.test_lab import ordered
from tests.api.test_patients import register
from tests.api.test_queue import booked_today, checked_in, refusal, stepped, today, walked_in
from tests.conftest import Outbox

API = "/api/v1"


def line(description: str = "Dressing", price: str = "150.00", **extra: Any) -> dict[str, Any]:
    return {"item_type": "procedure", "description": description, "unit_price": price, **extra}


async def raise_bill(
    client: AsyncClient,
    patient: dict[str, Any],
    *,
    items: list[dict[str, Any]] | None = None,
    key: str | None = None,
    **body: Any,
) -> Response:
    headers = {"Idempotency-Key": key} if key else {}
    return await client.post(
        f"{API}/invoices",
        json={"patient_id": patient["id"], "items": items or [line()], **body},
        headers=headers,
    )


async def raised(client: AsyncClient, patient: dict[str, Any], **body: Any) -> dict[str, Any]:
    response = await raise_bill(client, patient, **body)
    assert response.status_code == 201, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def pay(
    client: AsyncClient, bill: dict[str, Any], amount: str, method: str = "cash", **body: Any
) -> Response:
    key = body.pop("key", None)
    return await client.post(
        f"{API}/invoices/{bill['id']}/payments",
        json={"amount": amount, "method": method, **body},
        headers={"Idempotency-Key": key} if key else {},
    )


async def paid(
    client: AsyncClient, bill: dict[str, Any], amount: str, method: str = "cash", **body: Any
) -> dict[str, Any]:
    response = await pay(client, bill, amount, method, **body)
    assert response.status_code == 201, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def refund(
    client: AsyncClient, bill: dict[str, Any], amount: str, reason: str = "Test not done"
) -> Response:
    return await client.post(
        f"{API}/invoices/{bill['id']}/refunds",
        json={"amount": amount, "method": "cash", "reason": reason},
    )


async def void(
    client: AsyncClient, bill: dict[str, Any], reason: str = "Wrong patient"
) -> Response:
    return await client.post(f"{API}/invoices/{bill['id']}/void", json={"reason": reason})


async def one(client: AsyncClient, bill_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/invoices/{bill_id}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def listing(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/invoices", params=params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def starting(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/invoices/start", params=params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def summary(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/invoices/summary", params=params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def seen(
    client: AsyncClient, patient: dict[str, Any], doctor: dict[str, Any]
) -> dict[str, Any]:
    """A walk-in who has been in to the doctor and come out."""
    entry = await walked_in(client, patient, doctor)
    await stepped(client, entry["id"], "start")
    return await stepped(client, entry["id"], "complete")


async def a_desk(client: AsyncClient, outbox: Outbox) -> tuple[Clinic, dict[str, Any]]:
    """A clinic whose doctor charges 500, and 300 to see someone again, and a
    patient at the desk. The clinic admin is signed in."""
    clinic = await a_clinic(client, outbox)
    await client.patch(
        f"{API}/doctors/{clinic.doctor['id']}",
        json={"consultation_fee": "500.00", "follow_up_fee": "300.00"},
    )
    return clinic, await register(client)


class TestStartingABill:
    async def test_a_visit_starts_from_the_doctors_fee(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        entry = await seen(client, patient, clinic.doctor)

        found = await starting(client, queue_entry_id=entry["id"])

        assert found["patient"]["id"] == patient["id"]
        assert found["doctor"]["id"] == clinic.doctor["id"]
        assert found["visit"]["token"] == entry["token"]
        [first] = found["items"]
        assert first["item_type"] == "consultation"
        assert first["unit_price"] == "500.00"
        assert first["description"] == f"Consultation, {clinic.doctor['display_name']}"
        assert found["existing"] is None
        assert found["currency"] == "INR"

    async def test_someone_seen_by_the_same_doctor_lately_is_a_follow_up(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        earlier = await seen(client, patient, clinic.doctor)
        # Their last visit was three days ago, inside the clinic's week.
        await session.execute(
            update(QueueEntry)
            .where(QueueEntry.id == uuid.UUID(earlier["id"]))
            .values(token_date=today() - dt.timedelta(days=3))
        )
        await session.commit()
        again = await seen(client, patient, clinic.doctor)

        [first] = (await starting(client, queue_entry_id=again["id"]))["items"]
        assert first["unit_price"] == "300.00"
        assert first["description"].startswith("Follow-up consultation")

        # Outside the window, it is a fresh consultation again.
        await session.execute(
            update(QueueEntry)
            .where(QueueEntry.id == uuid.UUID(earlier["id"]))
            .values(token_date=today() - dt.timedelta(days=30))
        )
        await session.commit()
        [first] = (await starting(client, queue_entry_id=again["id"]))["items"]
        assert first["unit_price"] == "500.00"

    async def test_a_booked_follow_up_is_charged_as_one(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        appointment_id = await booked_today(session, client, patient, clinic.doctor)
        await client.patch(
            f"{API}/appointments/{appointment_id}", json={"appointment_type": "follow_up"}
        )
        entry = await checked_in(client, appointment_id)

        [first] = (await starting(client, queue_entry_id=entry["id"]))["items"]
        assert first["unit_price"] == "300.00"

    async def test_a_doctor_without_a_fee_falls_back_to_the_clinics(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        await client.patch(f"{API}/clinic/settings", json={"consultation_fee": "400.00"})
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        entry = await seen(client, patient, doctor)

        [first] = (await starting(client, queue_entry_id=entry["id"]))["items"]
        assert first["unit_price"] == "400.00"

    async def test_tests_ordered_at_the_visit_are_offered(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        entry = await walked_in(client, patient, clinic.doctor)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])
        await ordered(client, notes, test_code="cbc")
        await become(client, clinic.admin)

        found = await starting(client, queue_entry_id=entry["id"])
        assert found["lab_tests"] == ["Complete blood count"]

    async def test_a_bill_on_its_own_starts_empty(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        found = await starting(client, patient_id=patient["id"])
        assert (found["items"], found["visit"], found["doctor"]) == ([], None, None)

    async def test_the_bill_already_raised_is_pointed_to(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        entry = await seen(client, patient, clinic.doctor)
        bill = await raised(client, patient, queue_entry_id=entry["id"], issue=True)

        found = await starting(client, queue_entry_id=entry["id"])
        assert found["existing"] == bill["id"]
        assert found["existing_number"] == bill["invoice_number"]


class TestSums:
    async def test_the_bill_adds_up_and_money_is_a_string(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(
            client,
            patient,
            items=[
                line("Consultation", "500.00", item_type="consultation"),
                line("Dressing", "120.50", quantity=3),
            ],
            discount_amount="61.50",
            discount_reason="Staff family",
            notes="Change the dressing on Friday.",
        )

        assert bill["status"] == "draft"
        assert bill["invoice_number"] is None
        assert [item["amount"] for item in bill["items"]] == ["500.00", "361.50"]
        assert bill["subtotal"] == "861.50"
        assert bill["discount_amount"] == "61.50"
        assert bill["tax_amount"] == "0.00"
        assert bill["total"] == "800.00"
        assert bill["balance"] == "800.00"
        assert bill["headline"] == "Consultation and 1 more"
        assert bill["notes"] == "Change the dressing on Friday."
        assert bill["created_by"] == "Priya Nair"
        assert bill["can_edit"] is True

    async def test_tax_is_charged_at_the_clinics_rate_and_rounded_half_up(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        await client.patch(f"{API}/clinic/settings", json={"tax_percent": "18.00"})

        # 18% of 104.25 is 18.765, which is 18.77 on a bill.
        bill = await raised(client, patient, items=[line("Nebulisation", "104.25")])
        assert (bill["tax_percent"], bill["tax_amount"], bill["total"]) == (
            "18.00",
            "18.77",
            "123.02",
        )

        # A rate changed later does not reach a bill already made.
        await client.patch(f"{API}/clinic/settings", json={"tax_percent": "5.00"})
        again = await one(client, bill["id"])
        assert again["tax_amount"] == "18.77"

    async def test_tax_is_on_what_is_left_after_the_discount(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        await client.patch(f"{API}/clinic/settings", json={"tax_percent": "10.00"})
        bill = await raised(
            client,
            patient,
            items=[line("Procedure", "1000.00")],
            discount_amount="200.00",
            discount_reason="Senior citizen",
        )
        assert (bill["tax_amount"], bill["total"]) == ("80.00", "880.00")

    async def test_a_discount_needs_a_reason_and_cannot_pass_the_bill(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)

        no_reason = refusal(await raise_bill(client, patient, discount_amount="10.00"))
        assert no_reason["status"] == 422
        assert "discount_reason" in no_reason["fields"]

        too_much = refusal(
            await raise_bill(
                client, patient, discount_amount="150.01", discount_reason="Goodwill"
            )
        )
        assert too_much["code"] == "BILLING_INVALID_TOTAL"
        assert too_much["fields"]["discount_amount"] == (
            "The discount is more than the bill, which comes to ₹150.00."
        )

        # The whole bill waived is allowed, and comes to nothing.
        waived = await raised(
            client, patient, discount_amount="150.00", discount_reason="Camp patient"
        )
        assert waived["total"] == "0.00"

    @pytest.mark.parametrize(
        ("items", "field"),
        [
            ([], "items"),
            ([line(price="-1.00")], "items.0.unit_price"),
            ([line(price="10.005")], "items.0.unit_price"),
            ([line(price="1000000.01")], "items.0.unit_price"),
            ([line(quantity=0)], "items.0.quantity"),
            ([line(quantity=1000)], "items.0.quantity"),
            ([line(description="   ")], "items.0.description"),
            ([line(description="x" * 121)], "items.0.description"),
            ([line(item_type="massage")], "items.0.item_type"),
            ([line()] * 51, "items"),
        ],
    )
    async def test_a_line_that_makes_no_sense_is_refused(
        self, client: AsyncClient, outbox: Outbox, items: list[dict[str, Any]], field: str
    ) -> None:
        await sign_up(client)
        patient = await register(client)
        response = await client.post(
            f"{API}/invoices", json={"patient_id": patient["id"], "items": items}
        )
        found = refusal(response)
        assert found["status"] == 422
        assert field in found["fields"], found["fields"]

    async def test_a_bill_bigger_than_a_crore_is_refused(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        patient = await register(client)
        found = refusal(
            await raise_bill(client, patient, items=[line(price="1000000.00", quantity=11)])
        )
        assert found["code"] == "BILLING_INVALID_TOTAL"
        assert "₹1,10,00,000.00" in found["message"]


class TestIssuing:
    async def test_issuing_numbers_bills_by_financial_year_one_after_another(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        year = financial_year(today())

        draft = await raised(client, patient)
        first = await raised(client, patient, issue=True)
        issued = await client.post(f"{API}/invoices/{draft['id']}/issue")
        assert issued.status_code == 200, issued.text
        second = issued.json()["data"]

        assert first["invoice_number"] == f"INV/{year}/0001"
        assert second["invoice_number"] == f"INV/{year}/0002"
        assert first["status"] == "unpaid"
        assert first["issued_by"] == "Priya Nair"
        assert first["can_edit"] is False

        again = refusal(await client.post(f"{API}/invoices/{draft['id']}/issue"))
        assert again["code"] == "BILLING_LOCKED"

    async def test_a_thrown_away_draft_leaves_no_gap(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        draft = await raised(client, patient)
        assert (await client.delete(f"{API}/invoices/{draft['id']}")).status_code == 200
        assert (await client.get(f"{API}/invoices/{draft['id']}")).status_code == 404

        bill = await raised(client, patient, issue=True)
        assert bill["invoice_number"].endswith("/0001")

    async def test_each_clinic_counts_its_own_bills_with_its_own_prefix(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        await raised(client, patient, issue=True)

        await client.post(f"{API}/auth/logout")
        await sign_up(client, clinic_name="Lotus Clinic")
        await client.patch(f"{API}/clinic/settings", json={"invoice_prefix": "lc"})
        theirs = await register(client)
        bill = await raised(client, theirs, issue=True)
        assert bill["invoice_number"] == f"LC/{financial_year(today())}/0001"

    async def test_a_bill_for_nothing_is_paid_the_moment_it_is_issued(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(
            client, patient, items=[line("Review of reports", "0.00")], issue=True
        )
        assert (bill["status"], bill["balance"], bill["can_pay"]) == ("paid", "0.00", False)

    async def test_an_issued_bill_is_not_changed_or_thrown_away(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)

        changed = refusal(
            await client.patch(f"{API}/invoices/{bill['id']}", json={"notes": "Later"})
        )
        assert (changed["status"], changed["code"]) == (409, "BILLING_LOCKED")
        thrown = refusal(await client.delete(f"{API}/invoices/{bill['id']}"))
        assert thrown["code"] == "BILLING_LOCKED"

    async def test_a_draft_is_changed_and_worked_out_again(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        draft = await raised(client, patient)

        response = await client.patch(
            f"{API}/invoices/{draft['id']}",
            json={
                "items": [line("Injection", "80.00", quantity=2), line("Syringe", "10.00")],
                "discount_amount": "20.00",
                "discount_reason": "Regular",
            },
        )
        assert response.status_code == 200, response.text
        changed = response.json()["data"]
        assert [item["description"] for item in changed["items"]] == ["Injection", "Syringe"]
        assert (changed["subtotal"], changed["total"]) == ("170.00", "150.00")

        # Just the notes, and the rest stays as it was.
        noted = (
            await client.patch(f"{API}/invoices/{draft['id']}", json={"notes": "Paid by son"})
        ).json()["data"]
        assert (noted["total"], noted["notes"], noted["discount_reason"]) == (
            "150.00",
            "Paid by son",
            "Regular",
        )

        # Taking the discount off takes its reason with it.
        plain = (
            await client.patch(
                f"{API}/invoices/{draft['id']}", json={"discount_amount": "0.00"}
            )
        ).json()["data"]
        assert (plain["total"], plain["discount_reason"]) == ("170.00", None)


class TestOneBillPerVisit:
    async def test_a_visit_is_billed_once_until_its_bill_is_voided(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        entry = await seen(client, patient, clinic.doctor)
        bill = await raised(client, patient, queue_entry_id=entry["id"], issue=True)
        assert bill["visit"]["queue_entry_id"] == entry["id"]
        assert bill["doctor"]["id"] == clinic.doctor["id"]

        second = refusal(await raise_bill(client, patient, queue_entry_id=entry["id"]))
        assert (second["status"], second["code"]) == (409, "BILLING_ALREADY_BILLED")
        assert second["candidates"] == [
            {"id": bill["id"], "invoice_number": bill["invoice_number"], "status": "unpaid"}
        ]

        assert (await void(client, bill)).status_code == 200
        replacement = await raised(client, patient, queue_entry_id=entry["id"])
        assert replacement["visit"]["queue_entry_id"] == entry["id"]

    async def test_two_desks_billing_one_visit_at_once_make_one_bill(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        entry = await seen(client, patient, clinic.doctor)

        answers = await asyncio.gather(
            *(raise_bill(client, patient, queue_entry_id=entry["id"]) for _ in range(3))
        )
        assert sorted(answer.status_code for answer in answers) == [201, 409, 409]
        assert (await listing(client))["total"] == 1

    async def test_a_visit_belongs_to_its_own_patient(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        other = await register(client, first_name="Rohan", phone="9820099887")
        entry = await seen(client, patient, clinic.doctor)

        found = refusal(await raise_bill(client, other, queue_entry_id=entry["id"]))
        assert found["fields"]["queue_entry_id"] == "That visit is someone else's."

    async def test_the_queue_shows_the_desk_the_bill_and_the_doctor_nothing(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        entry = await seen(client, patient, clinic.doctor)
        bill = await raised(client, patient, queue_entry_id=entry["id"], issue=True)

        shown = (await client.get(f"{API}/queue/{entry['id']}")).json()["data"]
        assert shown["invoice"] == {
            "id": bill["id"],
            "invoice_number": bill["invoice_number"],
            "status": "unpaid",
        }

        await become(client, clinic.doctor_email)
        hidden = (await client.get(f"{API}/queue/{entry['id']}")).json()["data"]
        assert hidden["invoice"] is None
        day = (await client.get(f"{API}/queue")).json()["data"]
        assert all(each["invoice"] is None for lane in day["lanes"] for each in lane["done"])


class TestSameRequestTwice:
    async def test_the_same_request_again_answers_with_the_first_bill(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        key = uuid.uuid4().hex

        first = await raise_bill(client, patient, key=key, issue=True)
        again = await raise_bill(client, patient, key=key, issue=True)

        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json()["data"]["id"] == again.json()["data"]["id"]
        assert (await listing(client))["total"] == 1

    async def test_the_same_request_at_the_same_moment_still_makes_one(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        key = uuid.uuid4().hex
        answers = await asyncio.gather(
            *(raise_bill(client, patient, key=key) for _ in range(3))
        )
        assert {answer.status_code for answer in answers} <= {200, 201}
        assert len({answer.json()["data"]["id"] for answer in answers}) == 1

    async def test_a_payment_sent_twice_is_taken_once(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, items=[line(price="500.00")], issue=True)
        key = uuid.uuid4().hex

        answers = await asyncio.gather(
            *(pay(client, bill, "200.00", key=key) for _ in range(3))
        )
        assert {answer.status_code for answer in answers} == {201}
        found = await one(client, bill["id"])
        assert (found["amount_paid"], len(found["payments"])) == ("200.00", 1)

    @pytest.mark.parametrize("key", ["short", "has spaces in it", "x" * 65, "semi;colon"])
    async def test_a_key_that_is_not_one_is_refused(
        self, client: AsyncClient, outbox: Outbox, key: str
    ) -> None:
        _, patient = await a_desk(client, outbox)
        found = refusal(await raise_bill(client, patient, key=key))
        assert found["status"] == 422


class TestPayments:
    async def test_paid_in_parts_then_in_full(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, items=[line(price="800.00")], issue=True)

        part = await paid(client, bill, "300.00", "upi", reference="UPI 4411 2290")
        assert (part["status"], part["amount_paid"], part["balance"]) == (
            "partly_paid",
            "300.00",
            "500.00",
        )
        rest = await paid(client, bill, "500.00", "cash")
        assert (rest["status"], rest["balance"], rest["can_pay"]) == ("paid", "0.00", False)

        [first, second] = rest["payments"]
        assert (first["method"], first["reference"], first["received_by"]) == (
            "upi",
            "UPI 4411 2290",
            "Priya Nair",
        )
        assert (second["kind"], second["amount"]) == ("payment", "500.00")

    async def test_more_than_is_owed_is_refused_with_what_is(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, items=[line(price="1250.00")], issue=True)
        await paid(client, bill, "250.00")

        found = refusal(await pay(client, bill, "1000.01"))
        assert found["code"] == "BILLING_PAYMENT_EXCEEDS_BALANCE"
        assert found["fields"]["amount"] == "₹1,000.00 is all that is owed on this bill."

    async def test_a_paid_bill_takes_nothing_more(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)
        await paid(client, bill, "150.00")
        found = refusal(await pay(client, bill, "1.00"))
        assert (found["status"], found["code"]) == (409, "BILLING_ALREADY_PAID")

    async def test_taking_money_on_a_draft_issues_it(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        draft = await raised(client, patient)
        found = await paid(client, draft, "150.00", "card")
        assert found["status"] == "paid"
        assert found["invoice_number"].endswith("/0001")

    @pytest.mark.parametrize(
        ("amount", "method"),
        [("0", "cash"), ("-5.00", "cash"), ("5.001", "cash"), ("5", "gold")],
    )
    async def test_a_payment_that_makes_no_sense_is_refused(
        self, client: AsyncClient, outbox: Outbox, amount: str, method: str
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)
        assert refusal(await pay(client, bill, amount, method))["status"] == 422

    async def test_two_payments_racing_for_the_last_of_a_bill_take_it_once(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, items=[line(price="500.00")], issue=True)

        answers = await asyncio.gather(*(pay(client, bill, "500.00") for _ in range(3)))
        assert sorted(answer.status_code for answer in answers) == [201, 409, 409]
        assert (await one(client, bill["id"]))["amount_paid"] == "500.00"


class TestRefundsAndVoids:
    async def test_the_clinic_admin_gives_money_back_and_the_bill_says_so(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, items=[line(price="600.00")], issue=True)
        await paid(client, bill, "600.00")

        response = await refund(client, bill, "200.00", "Dressing not needed")
        assert response.status_code == 201, response.text
        found = response.json()["data"]
        assert (found["status"], found["refunded_amount"], found["balance"]) == (
            "paid",
            "200.00",
            "0.00",
        )
        back = found["payments"][-1]
        assert (back["kind"], back["note"]) == ("refund", "Dressing not needed")

        too_much = refusal(await refund(client, bill, "400.01"))
        assert too_much["code"] == "BILLING_REFUND_EXCEEDS_PAID"
        assert (
            too_much["fields"]["amount"] == "₹400.00 is all that has been taken on this bill."
        )

        rest = (await refund(client, bill, "400.00")).json()["data"]
        assert rest["status"] == "refunded"
        assert (rest["can_refund"], rest["can_void"]) == (False, True)

    async def test_a_bill_money_has_gone_back_on_takes_no_more(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, items=[line(price="600.00")], issue=True)
        await paid(client, bill, "300.00")
        await refund(client, bill, "100.00")

        found = refusal(await pay(client, bill, "100.00"))
        assert found["code"] == "BILLING_REFUNDED"
        assert (await one(client, bill["id"]))["can_pay"] is False

    async def test_a_refund_needs_a_reason_and_money_to_give_back(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)

        nothing = refusal(await refund(client, bill, "10.00"))
        assert (
            nothing["fields"]["amount"] == "Nothing has been taken on this bill to give back."
        )
        await paid(client, bill, "150.00")
        assert refusal(await refund(client, bill, "10.00", reason=""))["status"] == 422

    async def test_the_desk_does_not_give_money_back(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        desk = await invite_and_accept(client, role="receptionist", outbox=outbox)
        bill = await raised(client, patient, issue=True)
        await paid(client, bill, "150.00")

        await become(client, desk)
        found = refusal(await refund(client, bill, "150.00"))
        assert (found["status"], found["message"]) == (
            403,
            "Only the clinic admin can give money back.",
        )
        shown = await one(client, bill["id"])
        assert shown["can_refund"] is False
        # Nor void it with the money still taken: that is the admin's call.
        assert shown["can_void"] is False
        assert shown["void_blocked"] == (
            "₹150.00 is still taken on this bill. "
            "It has to be given back before the bill can be voided."
        )

    async def test_a_void_needs_a_reason_and_nothing_left_taken(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, items=[line(price="400.00")], issue=True)
        await paid(client, bill, "100.00")

        assert refusal(await void(client, bill, reason=""))["status"] == 422
        held = refusal(await void(client, bill))
        assert (held["status"], held["code"]) == (409, "BILLING_HAS_PAYMENTS")

        await refund(client, bill, "100.00")
        response = await void(client, bill, "Billed to the wrong patient")
        assert response.status_code == 200, response.text
        found = response.json()["data"]
        assert (found["status"], found["void_reason"], found["voided_by"]) == (
            "void",
            "Billed to the wrong patient",
            "Priya Nair",
        )
        assert (found["can_pay"], found["can_void"], found["can_refund"]) == (
            False,
            False,
            False,
        )

        twice = refusal(await void(client, bill))
        assert twice["code"] == "BILLING_INVOICE_VOIDED"
        assert refusal(await pay(client, bill, "10.00"))["code"] == "BILLING_INVOICE_VOIDED"

    async def test_an_unpaid_bill_is_voided_straight_away_and_a_draft_is_deleted_instead(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)
        assert (await void(client, bill)).status_code == 200

        draft = await raised(client, patient)
        found = refusal(await void(client, draft))
        assert found["message"] == "A draft has no number to void. Delete it instead."


class TestWhoMaySee:
    async def test_the_doctor_and_staff_have_no_part_in_bills(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)
        staff = await invite_and_accept(client, role="staff", outbox=outbox)

        for email in (clinic.doctor_email, staff):
            await become(client, email)
            assert (await client.get(f"{API}/invoices")).status_code == 403
            assert (await client.get(f"{API}/invoices/{bill['id']}")).status_code == 403
            assert (await raise_bill(client, patient)).status_code == 403
            assert (await pay(client, bill, "10.00")).status_code == 403

    async def test_the_desk_raises_and_takes_money(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        desk = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, desk)

        bill = await raised(client, patient, issue=True)
        found = await paid(client, bill, "150.00")
        assert found["status"] == "paid"

    async def test_another_clinics_bill_reads_as_missing(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)

        await client.post(f"{API}/auth/logout")
        await sign_up(client, clinic_name="Lotus Clinic")
        for response in (
            await client.get(f"{API}/invoices/{bill['id']}"),
            await client.get(f"{API}/invoices/{bill['id']}/pdf"),
            await pay(client, bill, "10.00"),
            await void(client, bill),
            await client.delete(f"{API}/invoices/{bill['id']}"),
        ):
            assert response.status_code == 404, response.text
        assert (await raise_bill(client, patient)).status_code == 404
        assert (await listing(client))["total"] == 0

    async def test_an_archived_record_takes_no_new_bill_but_pays_the_old_one(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)
        await client.post(f"{API}/patients/{patient['id']}/archive")

        found = refusal(await raise_bill(client, patient))
        assert found["code"] == "PATIENT_ARCHIVED"
        assert (await pay(client, bill, "150.00")).status_code == 201


class TestLists:
    async def test_bills_are_found_by_what_they_are_and_who_they_are_for(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        other = await register(client, first_name="Rohan", last_name="Iyer", phone="9820099887")
        draft = await raised(client, patient)
        owed = await raised(client, patient, issue=True)
        settled = await raised(client, other, issue=True)
        await paid(client, settled, "150.00")
        voided = await raised(client, other, issue=True)
        await void(client, voided)

        everything = await listing(client)
        assert everything["total"] == 4
        # Newest first, a draft by when it was made.
        assert [each["id"] for each in everything["items"]] == [
            voided["id"],
            settled["id"],
            owed["id"],
            draft["id"],
        ]
        counts = everything["counts"]
        assert (counts["draft"], counts["unpaid"], counts["paid"], counts["void"]) == (
            1,
            1,
            1,
            1,
        )

        assert [each["id"] for each in (await listing(client, show="to_collect"))["items"]] == [
            owed["id"]
        ]
        assert (await listing(client, show="drafts"))["items"][0]["id"] == draft["id"]
        assert (await listing(client, show="paid"))["items"][0]["id"] == settled["id"]
        assert (await listing(client, show="void"))["items"][0]["id"] == voided["id"]

        assert (await listing(client, q="iyer"))["total"] == 2
        assert (await listing(client, q="9820099887"))["total"] == 2
        assert (await listing(client, q=owed["invoice_number"]))["items"][0]["id"] == owed["id"]
        assert (await listing(client, q="100%_"))["total"] == 0
        theirs = await listing(client, patient_id=patient["id"])
        assert (theirs["total"], theirs["owed"]) == (2, "150.00")
        assert everything["owed"] == "150.00"

        day = today().isoformat()
        assert (await listing(client, **{"from": day, "to": day}))["total"] == 4
        yesterday = (today() - dt.timedelta(days=1)).isoformat()
        assert (await listing(client, **{"from": yesterday, "to": yesterday}))["total"] == 0
        backwards = refusal(
            await client.get(f"{API}/invoices", params={"from": day, "to": yesterday})
        )
        assert backwards["status"] == 422

        page = await listing(client, limit=3, offset=3)
        assert [each["id"] for each in page["items"]] == [draft["id"]]

    async def test_the_day_is_counted_by_how_it_was_paid(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        first = await raised(client, patient, items=[line(price="500.00")], issue=True)
        second = await raised(client, patient, items=[line(price="700.00")], issue=True)
        await raised(client, patient, items=[line(price="999.00")])
        await paid(client, first, "500.00", "cash")
        await paid(client, second, "300.00", "upi")
        await paid(client, second, "100.00", "cash")
        await refund(client, first, "50.00")

        found = await summary(client)
        by_method = {each["method"]: each for each in found["methods"]}
        assert by_method["cash"] == {
            "method": "cash",
            "received": "600.00",
            "refunded": "50.00",
            "net": "550.00",
            "count": 2,
        }
        assert by_method["upi"]["net"] == "300.00"
        assert list(by_method) == ["cash", "upi"]
        assert (found["received"], found["refunded"], found["net"]) == (
            "900.00",
            "50.00",
            "850.00",
        )
        # Drafts are not billed yet.
        assert (found["bills_issued"], found["billed"]) == (2, "1200.00")
        assert (found["outstanding"], found["outstanding_bills"]) == ("300.00", 1)

        quiet = await summary(client, date=(today() - dt.timedelta(days=1)).isoformat())
        assert (quiet["methods"], quiet["net"], quiet["bills_issued"]) == ([], "0.00", 0)
        # What is owed is owed whichever day is asked about.
        assert quiet["outstanding"] == "300.00"

    async def test_patients_seen_without_a_bill_are_listed_until_billed(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        other = await register(client, first_name="Rohan", phone="9820099887")
        first = await seen(client, patient, clinic.doctor)
        second = await seen(client, other, clinic.doctor)
        waiting = await walked_in(
            client,
            await register(
                client,
                first_name="Kiran",
                last_name="Bose",
                phone="9820055555",
                date_of_birth="1990-01-01",
            ),
            clinic.doctor,
        )

        found = (await client.get(f"{API}/invoices/unbilled")).json()["data"]
        ids = [each["queue_entry_id"] for each in found["items"]]
        assert ids == [second["id"], first["id"]]
        assert waiting["id"] not in ids

        bill = await raised(client, other, queue_entry_id=second["id"], issue=True)
        found = (await client.get(f"{API}/invoices/unbilled")).json()["data"]
        assert [each["queue_entry_id"] for each in found["items"]] == [first["id"]]

        await void(client, bill)
        found = (await client.get(f"{API}/invoices/unbilled")).json()["data"]
        assert len(found["items"]) == 2

    async def test_what_the_clinic_charged_before_is_offered_at_its_last_price(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        await raised(client, patient, items=[line("Dressing", "150.00")])
        await raised(client, patient, items=[line("Dressing", "180.00"), line("ECG", "300.00")])
        voided = await raised(client, patient, items=[line("Plaster", "900.00")], issue=True)
        await void(client, voided)

        found = (await client.get(f"{API}/invoices/lines")).json()["data"]
        assert found[0] == {
            "item_type": "procedure",
            "description": "Dressing",
            "unit_price": "180.00",
            "times": 2,
        }
        assert [each["description"] for each in found] == ["Dressing", "ECG"]

        typed = (await client.get(f"{API}/invoices/lines", params={"q": "ec"})).json()["data"]
        assert [each["description"] for each in typed] == ["ECG"]


class TestPrinting:
    async def test_an_issued_bill_prints_and_a_draft_does_not(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        await client.patch(f"{API}/clinic/settings", json={"gstin": "27abcde1234f1z5"})
        bill = await raised(
            client,
            patient,
            items=[line("Dressing", "150.00"), line("Injection", "80.00", quantity=2)],
            discount_amount="10.00",
            discount_reason="Regular",
            issue=True,
        )
        await paid(client, bill, "100.00", "upi", reference="4411")

        response = await client.get(f"{API}/invoices/{bill['id']}/pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
        assert (
            bill["invoice_number"].replace("/", "-") in response.headers["content-disposition"]
        )

        await refund(client, bill, "100.00")
        await void(client, bill)
        assert (await client.get(f"{API}/invoices/{bill['id']}/pdf")).status_code == 200

        draft = await raised(client, patient)
        assert (await client.get(f"{API}/invoices/{draft['id']}/pdf")).status_code == 422


class TestClinicSettings:
    async def test_a_gstin_is_checked_and_can_be_taken_off(self, client: AsyncClient) -> None:
        await sign_up(client)
        settings = f"{API}/clinic/settings"

        assert (await client.get(settings)).json()["data"]["gstin"] == ""
        wrong = refusal(await client.patch(settings, json={"gstin": "27ABCDE1234"}))
        assert wrong["status"] == 422

        kept = (await client.patch(settings, json={"gstin": " 27abcde1234f1z5 "})).json()
        assert kept["data"]["gstin"] == "27ABCDE1234F1Z5"
        gone = (await client.patch(settings, json={"gstin": ""})).json()
        assert gone["data"]["gstin"] == ""

    async def test_a_prefix_is_letters_digits_and_dashes(self, client: AsyncClient) -> None:
        await sign_up(client)
        settings = f"{API}/clinic/settings"
        wrong = refusal(await client.patch(settings, json={"invoice_prefix": "IN/V"}))
        assert wrong["fields"]["invoice_prefix"] == (
            "Use letters, digits and dashes only, like INV or LC-1."
        )
        kept = (await client.patch(settings, json={"invoice_prefix": "sfc-b"})).json()
        assert kept["data"]["invoice_prefix"] == "SFC-B"


class TestWords:
    @pytest.mark.parametrize(
        ("day", "year"),
        [
            (dt.date(2026, 3, 31), "2025-26"),
            (dt.date(2026, 4, 1), "2026-27"),
            (dt.date(2099, 12, 31), "2099-00"),
        ],
    )
    def test_the_financial_year_turns_in_april(self, day: dt.date, year: str) -> None:
        assert financial_year(day) == year

    @pytest.mark.parametrize(
        ("amount", "words"),
        [
            ("0", "₹0.00"),
            ("999.5", "₹999.50"),
            ("1000", "₹1,000.00"),
            ("123456.78", "₹1,23,456.78"),
            ("10000000", "₹1,00,00,000.00"),
            ("-1500", "-₹1,500.00"),
        ],
    )
    def test_rupees_are_grouped_the_indian_way(self, amount: str, words: str) -> None:
        assert rupees(Decimal(amount)) == words
