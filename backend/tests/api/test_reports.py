"""How the clinic has been doing, over whatever stretch of days is asked for.

The visits and the money are made through the API the way the desk makes
them, and then moved back in time in the database, because no endpoint will
let anybody check a patient in for last Tuesday.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invoice, Patient, Payment, QueueEntry
from tests.api.test_appointments import KOLKATA, doctor_with_hours
from tests.api.test_billing import line, paid, raised, refund
from tests.api.test_clinic import invite_and_accept, sign_up
from tests.api.test_consultations import a_clinic, become, opened
from tests.api.test_dashboard import patient
from tests.api.test_lab import ordered
from tests.api.test_queue import stepped, today, walked_in
from tests.conftest import Outbox

API = "/api/v1"


async def report(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await ask(client, **params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def ask(client: AsyncClient, **params: Any) -> Response:
    return await client.get(f"{API}/reports/summary", params=params or {"range": "week"})


async def seen(
    client: AsyncClient, who: dict[str, Any], doctor: dict[str, Any], **walk: Any
) -> dict[str, Any]:
    """A patient who walked in, was called through and went home."""
    entry = await walked_in(client, who, doctor, **walk)
    await stepped(client, entry["id"], "start")
    return await stepped(client, entry["id"], "complete")


async def never_stayed(
    client: AsyncClient, who: dict[str, Any], doctor: dict[str, Any]
) -> dict[str, Any]:
    entry = await walked_in(client, who, doctor)
    return await stepped(client, entry["id"], "no-show")


async def visit_moved(session: AsyncSession, entry: dict[str, Any], days: int) -> None:
    """Puts a visit back in time, day and clock together."""
    back = dt.timedelta(days=days)
    await session.execute(
        update(QueueEntry)
        .where(QueueEntry.id == uuid.UUID(entry["id"]))
        .values(
            token_date=QueueEntry.token_date - back,
            checked_in_at=QueueEntry.checked_in_at - back,
            called_at=QueueEntry.called_at - back,
            started_at=QueueEntry.started_at - back,
            completed_at=QueueEntry.completed_at - back,
        )
    )
    await session.commit()


async def money_moved(session: AsyncSession, bill: dict[str, Any], days: int) -> None:
    """Puts a bill and everything taken against it back in time."""
    back = dt.timedelta(days=days)
    invoice_id = uuid.UUID(bill["id"])
    await session.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id)
        .values(issued_at=Invoice.issued_at - back)
    )
    await session.execute(
        update(Payment)
        .where(Payment.invoice_id == invoice_id)
        .values(received_at=Payment.received_at - back)
    )
    await session.commit()


async def registered_moved(session: AsyncSession, who: dict[str, Any], days: int) -> None:
    await session.execute(
        update(Patient)
        .where(Patient.id == uuid.UUID(who["id"]))
        .values(created_at=Patient.created_at - dt.timedelta(days=days))
    )
    await session.commit()


def day_in(found: dict[str, Any], day: dt.date) -> dict[str, Any]:
    return next(each for each in found["days"] if each["date"] == day.isoformat())


def doctor_in(found: dict[str, Any], doctor: dict[str, Any]) -> dict[str, Any]:
    return next(each for each in found["doctors"] if each["doctor"]["id"] == doctor["id"])


class TestTheStretchAsked:
    async def test_today_is_one_day(self, client: AsyncClient) -> None:
        await sign_up(client)
        found = await report(client, range="today")
        assert found["span"]["days"] == 1
        assert found["span"]["first_day"] == found["span"]["last_day"] == today().isoformat()
        assert found["span"]["label"] == "Today"

    async def test_a_week_is_seven_days_ending_today(self, client: AsyncClient) -> None:
        await sign_up(client)
        found = await report(client, range="week")
        assert found["span"]["days"] == 7
        assert found["span"]["last_day"] == today().isoformat()
        assert found["span"]["first_day"] == (today() - dt.timedelta(days=6)).isoformat()
        assert len(found["days"]) == 7

    async def test_a_month_back_is_thirty_days(self, client: AsyncClient) -> None:
        await sign_up(client)
        found = await report(client, range="month")
        assert found["span"]["days"] == 30
        assert len(found["days"]) == 30

    async def test_this_month_starts_on_the_first(self, client: AsyncClient) -> None:
        await sign_up(client)
        found = await report(client, range="this_month")
        assert found["span"]["first_day"] == today().replace(day=1).isoformat()
        assert found["span"]["last_day"] == today().isoformat()

    async def test_last_month_is_the_whole_of_it(self, client: AsyncClient) -> None:
        await sign_up(client)
        found = await report(client, range="last_month")
        last_day = today().replace(day=1) - dt.timedelta(days=1)
        assert found["span"]["last_day"] == last_day.isoformat()
        assert found["span"]["first_day"] == last_day.replace(day=1).isoformat()
        assert found["span"]["days"] == last_day.day

    async def test_dates_of_your_own(self, client: AsyncClient) -> None:
        await sign_up(client)
        first = today() - dt.timedelta(days=3)
        found = await report(client, range="custom", **{"from": first.isoformat()}, to=today())
        assert found["span"]["days"] == 4
        assert found["span"]["label"] == "Chosen dates"

    async def test_the_last_day_may_not_come_first(self, client: AsyncClient) -> None:
        await sign_up(client)
        response = await ask(
            client,
            range="custom",
            **{"from": today().isoformat()},
            to=(today() - dt.timedelta(days=1)).isoformat(),
        )
        assert response.status_code == 422
        assert response.json()["error"]["fields"]["to"]

    async def test_more_than_a_year_is_refused(self, client: AsyncClient) -> None:
        await sign_up(client)
        response = await ask(
            client,
            range="custom",
            **{"from": (today() - dt.timedelta(days=400)).isoformat()},
            to=today().isoformat(),
        )
        assert response.status_code == 422

    async def test_your_own_dates_with_no_dates(self, client: AsyncClient) -> None:
        await sign_up(client)
        response = await ask(client, range="custom")
        assert response.status_code == 422
        assert response.json()["error"]["fields"]["from"]

    async def test_a_range_nobody_offers(self, client: AsyncClient) -> None:
        await sign_up(client)
        response = await ask(client, range="since-the-war")
        assert response.status_code == 422


class TestWhatItCounts:
    async def test_a_visit_today_is_counted_today(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        await seen(client, await patient(client, "Asha"), doctor)
        found = await report(client, range="today")
        assert found["seen"] == 1
        assert found["walk_ins"] == 1
        assert day_in(found, today())["seen"] == 1

    async def test_somebody_who_never_stayed_is_not_counted_as_seen(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        await never_stayed(client, await patient(client, "Bina"), doctor)
        found = await report(client, range="today")
        assert found["seen"] == 0
        assert found["no_shows"] == 1

    async def test_every_day_in_the_stretch_is_there_even_the_empty_ones(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        entry = await seen(client, await patient(client, "Chitra"), doctor)
        await visit_moved(session, entry, days=3)
        found = await report(client, range="week")
        assert len(found["days"]) == 7
        assert day_in(found, today() - dt.timedelta(days=3))["seen"] == 1
        assert day_in(found, today())["seen"] == 0
        assert found["seen"] == 1

    async def test_a_visit_outside_the_stretch_is_left_out(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        entry = await seen(client, await patient(client, "Divya"), doctor)
        await visit_moved(session, entry, days=10)
        assert (await report(client, range="week"))["seen"] == 0
        assert (await report(client, range="month"))["seen"] == 1

    async def test_new_patients_are_counted_on_the_day_they_were_registered(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        await patient(client, "Esha")
        old = await patient(client, "Farida")
        await registered_moved(session, old, days=40)
        found = await report(client, range="week")
        assert found["new_patients"] == 1
        assert day_in(found, today())["registered"] == 1

    async def test_what_the_stretch_before_it_did(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        await seen(client, await patient(client, "Gita"), doctor)
        earlier = await seen(client, await patient(client, "Hema"), doctor)
        await visit_moved(session, earlier, days=8)
        found = await report(client, range="week")
        assert found["seen"] == 1
        assert found["before"]["seen"] == 1

    async def test_when_people_come_is_counted_by_the_hour(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        await seen(client, await patient(client, "Ila"), doctor)
        found = await report(client, range="today")
        assert sum(hour["seen"] for hour in found["hours"]) == 1
        hour = dt.datetime.now(KOLKATA).hour
        assert found["hours"][0]["hour"] == hour


class TestTheMoney:
    async def test_what_came_in_by_how_it_was_paid(self, client: AsyncClient) -> None:
        await sign_up(client)
        who = await patient(client, "Jaya")
        bill = await raised(client, who, items=[line(price="500.00")], issue=True)
        await paid(client, bill, "200.00", "cash")
        await paid(client, bill, "300.00", "upi")
        found = await report(client, range="today")
        by_method = {each["method"]: each for each in found["methods"]}
        assert by_method["cash"]["net"] == "200.00"
        assert by_method["upi"]["net"] == "300.00"
        assert found["net"] == "500.00"
        assert found["per_patient"] == "0.00"

    async def test_money_given_back_comes_off_the_takings(self, client: AsyncClient) -> None:
        await sign_up(client)
        who = await patient(client, "Kavita")
        bill = await raised(client, who, items=[line(price="500.00")], issue=True)
        await paid(client, bill, "500.00", "cash")
        assert (await refund(client, bill, "200.00")).status_code == 201
        found = await report(client, range="today")
        assert found["received"] == "500.00"
        assert found["refunded"] == "200.00"
        assert found["net"] == "300.00"
        assert day_in(found, today())["collected"] == "300.00"

    async def test_what_is_still_owed_ignores_the_dates_asked_for(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        who = await patient(client, "Lata")
        bill = await raised(client, who, items=[line(price="400.00")], issue=True)
        await money_moved(session, bill, days=90)
        found = await report(client, range="today")
        assert found["bills_issued"] == 0
        assert found["outstanding"] == "400.00"
        assert found["outstanding_bills"] == 1

    async def test_the_day_reads_the_same_from_billing_and_from_reports(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        who = await patient(client, "Mala")
        bill = await raised(client, who, items=[line(price="750.00")], issue=True)
        await paid(client, bill, "750.00", "card")
        found = await report(client, range="today")
        day = (await client.get(f"{API}/invoices/summary")).json()["data"]
        for figure in ("received", "refunded", "net", "online", "billed", "outstanding"):
            assert found[figure] == day[figure], figure
        assert found["bills_issued"] == day["bills_issued"]
        assert found["methods"] == day["methods"]

    async def test_a_bill_that_was_voided_is_not_counted_as_billed(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        who = await patient(client, "Nina")
        bill = await raised(client, who, items=[line(price="300.00")], issue=True)
        assert (
            await client.post(f"{API}/invoices/{bill['id']}/void", json={"reason": "Wrong one"})
        ).status_code == 200
        found = await report(client, range="today")
        assert found["bills_issued"] == 0
        assert found["billed"] == "0.00"
        assert found["charges"] == []

    async def test_what_the_bills_were_for_folds_the_wording_together(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        who = await patient(client, "Omana")
        await raised(client, who, items=[line("Dressing", "150.00")], issue=True)
        await raised(client, who, items=[line("dressing", "150.00")], issue=True)
        found = await report(client, range="today")
        assert len(found["charges"]) == 1
        assert found["charges"][0]["times"] == 2
        assert found["charges"][0]["amount"] == "300.00"


class TestEachDoctor:
    async def test_their_patients_and_their_money(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        other = await doctor_with_hours(client, first_name="Brinda")
        await seen(client, await patient(client, "Padma"), clinic.doctor)
        who = await patient(client, "Qamar")
        visit = await seen(client, who, clinic.doctor)
        await seen(client, await patient(client, "Rekha"), other)

        bill = await raised(
            client,
            who,
            items=[line(price="600.00")],
            queue_entry_id=visit["id"],
            issue=True,
        )
        await paid(client, bill, "600.00", "cash")

        found = await report(client, range="today")
        assert next(each["doctor"]["id"] for each in found["doctors"]) == clinic.doctor["id"]
        theirs = doctor_in(found, clinic.doctor)
        assert theirs["seen"] == 2
        assert theirs["billed"] == "600.00"
        assert theirs["collected"] == "600.00"
        assert doctor_in(found, other)["seen"] == 1
        assert doctor_in(found, other)["billed"] == "0.00"

    async def test_how_long_a_visit_took(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        await seen(client, await patient(client, "Tara"), doctor)
        found = await report(client, range="today")
        # Started and finished in the same instant, so far as the clock here
        # is concerned: the point is that it was timed at all.
        assert doctor_in(found, doctor)["average_minutes"] == 0

    async def test_a_doctor_nobody_saw_is_not_listed(self, client: AsyncClient) -> None:
        await sign_up(client)
        await doctor_with_hours(client)
        assert (await report(client, range="today"))["doctors"] == []


class TestWhatWasOrdered:
    async def test_tests_are_counted_by_name(self, client: AsyncClient, outbox: Outbox) -> None:
        clinic = await a_clinic(client, outbox)
        who = await patient(client, "Usha")
        entry = await walked_in(client, who, clinic.doctor)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])
        await ordered(client, notes, test_name="Complete blood count")
        await ordered(client, notes, test_name="Vitamin D")
        found = await report(client, range="today")
        assert {each["name"]: each["times"] for each in found["tests"]} == {
            "Complete blood count": 1,
            "Vitamin D": 1,
        }

    async def test_a_cancelled_order_is_not_counted(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        who = await patient(client, "Vidya")
        entry = await walked_in(client, who, clinic.doctor)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])
        order = await ordered(client, notes, test_name="Chest X-ray")
        called_off = await client.post(
            f"{API}/lab-orders/{order['id']}/cancel", json={"reason": "Not needed after all"}
        )
        assert called_off.status_code == 200, called_off.text
        assert (await report(client, range="today"))["tests"] == []


class TestWhoMayRead:
    async def test_the_desk_may_not(self, client: AsyncClient, outbox: Outbox) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, address)
        assert (await ask(client, range="week")).status_code == 403

    async def test_a_doctor_sees_their_own_patients_only(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        other = await doctor_with_hours(client, first_name="Charu")
        await seen(client, await patient(client, "Wasim"), clinic.doctor)
        await seen(client, await patient(client, "Xena"), other)
        await seen(client, await patient(client, "Yamini"), other)

        assert (await report(client, range="today"))["seen"] == 3

        await become(client, clinic.doctor_email)
        found = await report(client, range="today")
        assert found["view"] == "doctor"
        assert found["doctor"]["id"] == clinic.doctor["id"]
        assert found["seen"] == 1
        assert [each["doctor"]["id"] for each in found["doctors"]] == [clinic.doctor["id"]]

    async def test_a_doctors_account_with_no_profile_has_nothing_to_report(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="doctor", outbox=outbox)
        await become(client, address)
        found = await report(client, range="week")
        assert found["view"] == "unlinked"
        assert found["seen"] == 0
        assert found["days"] == []

    async def test_another_clinics_figures_never_show(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        await seen(client, await patient(client, "Zoya"), doctor)
        who = await patient(client, "Anjali")
        bill = await raised(client, who, items=[line(price="900.00")], issue=True)
        await paid(client, bill, "900.00", "cash")

        await client.post(f"{API}/auth/logout")
        await sign_up(client)
        found = await report(client, range="month")
        assert found["seen"] == 0
        assert found["net"] == "0.00"
        assert found["outstanding"] == "0.00"
        assert found["doctors"] == []


class TestTheDayBook:
    async def test_every_payment_gets_a_line(self, client: AsyncClient) -> None:
        await sign_up(client)
        who = await patient(client, "Bhavna")
        bill = await raised(client, who, items=[line(price="500.00")], issue=True)
        await paid(client, bill, "500.00", "upi", reference="UPI-99")
        assert (await refund(client, bill, "100.00")).status_code == 201

        response = await client.get(f"{API}/reports/day-book.csv", params={"range": "today"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]

        rows = list(csv.reader(io.StringIO(response.text.lstrip("﻿"))))
        assert rows[0][:4] == ["Date", "Time", "Bill", "Patient"]
        kinds = [row[5] for row in rows[1:]]
        assert kinds == ["Payment", "Refund"]
        assert rows[1][8] == "500.00"
        assert rows[1][9] == "UPI-99"
        assert rows[2][8] == "100.00"

    async def test_a_name_a_spreadsheet_would_run_is_written_as_text(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        who = await patient(client, "=cmd|'/c calc'!A0")
        bill = await raised(client, who, items=[line(price="100.00")], issue=True)
        await paid(client, bill, "100.00", "cash")
        response = await client.get(f"{API}/reports/day-book.csv", params={"range": "today"})
        rows = list(csv.reader(io.StringIO(response.text.lstrip("﻿"))))
        assert rows[1][3].startswith("'=cmd")

    async def test_the_desk_may_not_download_it(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, address)
        response = await client.get(f"{API}/reports/day-book.csv", params={"range": "today"})
        assert response.status_code == 403

    async def test_a_doctor_gets_only_their_own_lines(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        theirs = await patient(client, "Charulata")
        visit = await seen(client, theirs, clinic.doctor)
        mine = await raised(
            client,
            theirs,
            items=[line(price="400.00")],
            queue_entry_id=visit["id"],
            issue=True,
        )
        await paid(client, mine, "400.00", "cash")
        nobodys = await patient(client, "Deepa")
        loose = await raised(client, nobodys, items=[line(price="250.00")], issue=True)
        await paid(client, loose, "250.00", "cash")

        await become(client, clinic.doctor_email)
        response = await client.get(f"{API}/reports/day-book.csv", params={"range": "today"})
        rows = list(csv.reader(io.StringIO(response.text.lstrip("﻿"))))
        assert [row[8] for row in rows[1:]] == ["400.00"]


@pytest.mark.parametrize("path", ["/reports/summary", "/reports/day-book.csv"])
async def test_a_stranger_is_turned_away(client: AsyncClient, path: str) -> None:
    assert (await client.get(f"{API}{path}", params={"range": "week"})).status_code == 401
