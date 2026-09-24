"""Notices: who hears about what, and nobody else."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Notification
from tests.api import test_payment_links
from tests.api.test_appointments import book
from tests.api.test_billing import a_desk, raised, void
from tests.api.test_clinic import invite_and_accept, sign_up
from tests.api.test_consultations import a_clinic, become, member_id
from tests.api.test_lab import in_the_room, ordered, reported
from tests.api.test_patients import register
from tests.api.test_payment_links import (
    FakeGateway,
    confirm,
    handshake,
    linked,
    opened_by_patient,
    token_from,
)
from tests.conftest import Outbox

API = "/api/v1"
AUTH = "/api/v1/auth"

# The stand-in for Razorpay, borrowed from where it is defined.
gateway = test_payment_links.gateway


async def notices(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/notifications", params=params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


def kinds(found: dict[str, Any]) -> list[str]:
    return [notice["kind"] for notice in found["items"]]


class TestTheDoctorHears:
    async def test_about_a_booking_made_by_the_desk(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        patient = await register(client, first_name="Asha", last_name="Rao")
        made = await book(client, patient, clinic.doctor, reason="Cough for a week")

        assert "appointment_booked" not in kinds(await notices(client))
        await become(client, clinic.doctor_email)
        found = await notices(client)

        assert found["unread"] == 1
        notice = found["items"][0]
        assert notice["kind"] == "appointment_booked"
        assert notice["title"].startswith("Asha Rao booked for ")
        assert notice["body"] == "Cough for a week"
        assert notice["link"] == f"/appointments/{made['id']}"

    async def test_not_about_one_they_booked_themselves(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        patient = await register(client)
        await become(client, clinic.doctor_email)

        await book(client, patient, clinic.doctor)

        assert (await notices(client))["items"] == []

    async def test_about_a_move_and_a_cancellation(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        patient = await register(client)
        made = await book(client, patient, clinic.doctor)

        await client.patch(f"{API}/appointments/{made['id']}", json={"start_time": "10:00"})
        await client.patch(f"{API}/appointments/{made['id']}", json={"notes": "Bring reports"})
        await client.post(
            f"{API}/appointments/{made['id']}/cancel", json={"reason": "Feeling better"}
        )

        await become(client, clinic.doctor_email)
        found = await notices(client)
        assert kinds(found) == [
            "appointment_cancelled",
            "appointment_moved",
            "appointment_booked",
        ]
        assert found["items"][0]["body"] == "Feeling better"

    async def test_when_a_result_comes_in_and_only_the_first_time(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        order = await ordered(client, notes, test_code="cbc")
        await become(client, clinic.admin)

        await reported(client, order["id"], findings="Within normal limits.")
        await reported(client, order["id"], findings="Within normal limits, rechecked.")

        await become(client, clinic.doctor_email)
        found = await notices(client)
        assert kinds(found) == ["lab_result"]
        assert found["items"][0]["link"] == f"/lab/{order['id']}"

    async def test_nothing_once_suspended(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        clinic = await a_clinic(client, outbox)
        doctor_account = await member_id(client, clinic.doctor_email)
        await client.post(f"{API}/staff/{doctor_account}/suspend")

        await book(client, await register(client), clinic.doctor)

        held = await session.scalar(
            select(Notification.id).where(Notification.user_id == uuid.UUID(doctor_account))
        )
        assert held is None


class TestTheClinicHears:
    async def test_a_voided_bill_reaches_the_other_admins(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        second = await invite_and_accept(client, role="clinic-admin", outbox=outbox)
        bill = await raised(client, patient, issue=True)

        await void(client, bill, "Raised against the wrong patient")

        assert "bill_voided" not in kinds(await notices(client))
        await become(client, second)
        found = await notices(client)
        assert kinds(found) == ["bill_voided"]
        assert found["items"][0]["body"].endswith("Raised against the wrong patient")

    async def test_somebody_joining_and_a_role_changing(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="staff", outbox=outbox)

        joined = await notices(client)
        assert kinds(joined) == ["staff_joined"]
        assert joined["items"][0]["title"] == "Joiner Person joined as staff"

        await client.patch(
            f"{API}/staff/{await member_id(client, address)}/role",
            json={"role_slug": "receptionist"},
        )
        await become(client, address)
        found = await notices(client)
        assert kinds(found) == ["role_changed"]
        assert found["items"][0]["title"].endswith("made you receptionist")

    async def test_an_online_payment_reaches_whoever_reads_bills(
        self, client: AsyncClient, outbox: Outbox, gateway: FakeGateway
    ) -> None:
        clinic, patient = await a_desk(client, outbox)
        desk = await invite_and_accept(client, role="receptionist", outbox=outbox)
        bill = await raised(client, patient, issue=True)
        token = token_from((await linked(client, bill))["url"])
        order = (await opened_by_patient(client, token)).json()["data"]["order_id"]
        payment = gateway.pays(order)

        await confirm(client, token, handshake(order, payment))
        await confirm(client, token, handshake(order, payment))

        assert kinds(await notices(client)).count("paid_online") == 1
        await become(client, desk)
        assert kinds(await notices(client)) == ["paid_online"]
        await become(client, clinic.doctor_email)
        assert "paid_online" not in kinds(await notices(client))


class TestReadingThem:
    async def test_one_then_all(self, client: AsyncClient, outbox: Outbox) -> None:
        clinic = await a_clinic(client, outbox)
        for first_name, phone, start in (
            ("Asha", "9820040001", "09:00"),
            ("Kabir", "9820040002", "09:30"),
            ("Meera", "9820040003", "10:00"),
        ):
            patient = await register(client, first_name=first_name, phone=phone)
            await book(client, patient, clinic.doctor, start_time=start)
        await become(client, clinic.doctor_email)

        first = (await notices(client))["items"][0]
        read = await client.post(f"{API}/notifications/{first['id']}/read")
        assert read.json()["data"]["read_at"] is not None
        assert (await client.get(f"{API}/notifications/unread")).json()["data"]["unread"] == 2
        assert len((await notices(client, show="unread"))["items"]) == 2

        await client.post(f"{API}/notifications/read-all")
        assert (await notices(client))["unread"] == 0

    async def test_a_page_at_a_time(self, client: AsyncClient, session: AsyncSession) -> None:
        signed = await sign_up(client)
        me = uuid.UUID(signed["user"]["id"])
        clinic = uuid.UUID(signed["organization"]["id"])
        session.add_all(
            Notification(
                organization_id=clinic, user_id=me, kind="role_changed", title=f"Notice {n}"
            )
            for n in range(25)
        )
        await session.commit()

        first = await notices(client)
        assert len(first["items"]) == 20
        assert first["more"] is True
        rest = await notices(client, before=first["items"][-1]["id"])
        assert len(rest["items"]) == 5
        assert rest["more"] is False
        assert {n["id"] for n in first["items"]}.isdisjoint(n["id"] for n in rest["items"])

    async def test_nobody_reads_or_marks_anybody_elses(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        await book(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        theirs = (await notices(client))["items"][0]["id"]

        await become(client, clinic.admin)
        assert theirs not in [notice["id"] for notice in (await notices(client))["items"]]
        refused = await client.post(f"{API}/notifications/{theirs}/read")
        assert refused.status_code == 404
        await client.post(f"{API}/notifications/read-all")

        await become(client, clinic.doctor_email)
        assert (await notices(client))["unread"] == 1


class TestByEmail:
    async def test_each_role_is_offered_only_what_can_reach_it(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        admin = await client.get(f"{API}/notifications/preferences")
        offered = [kind["kind"] for kind in admin.json()["data"]["kinds"]]
        assert "bill_voided" in offered
        assert "appointment_booked" not in offered

        await become(client, clinic.doctor_email)
        doctor = await client.get(f"{API}/notifications/preferences")
        offered = [kind["kind"] for kind in doctor.json()["data"]["kinds"]]
        assert offered[:4] == [
            "appointment_booked",
            "appointment_moved",
            "appointment_cancelled",
            "lab_result",
        ]
        assert "paid_online" not in offered
        refused = await client.put(
            f"{API}/notifications/preferences", json={"kind": "bill_voided", "email": True}
        )
        assert refused.status_code == 422

    async def test_chosen_kinds_are_emailed_once_saved(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        clinic = await a_clinic(client, outbox)
        await become(client, clinic.doctor_email)
        chosen = await client.put(
            f"{API}/notifications/preferences",
            json={"kind": "appointment_booked", "email": True},
        )
        assert chosen.status_code == 200
        booked = next(
            k for k in chosen.json()["data"]["kinds"] if k["kind"] == "appointment_booked"
        )
        assert booked["email"] is True
        await become(client, clinic.admin)
        before = len(outbox.messages)

        await book(
            client, await register(client, first_name="Asha", phone="9820040011"), clinic.doctor
        )
        dropped = await book(
            client,
            await register(client, first_name="Kabir"),
            clinic.doctor,
            start_time="12:00",
        )
        await client.post(
            f"{API}/appointments/{dropped['id']}/cancel", json={"reason": "Clash"}
        )

        # Bookings were asked for by email; the cancellation stays in the app.
        sent = outbox.messages[before:]
        assert [message.to for message in sent] == [clinic.doctor_email] * 2
        assert sent[0].subject.startswith("Asha")
        assert f"{get_settings().app_url}/appointments/" in sent[0].action_url
        stamped = await session.scalars(
            select(Notification.sent_at).where(Notification.kind == "appointment_booked")
        )
        assert all(stamp is not None for stamp in stamped)
        await become(client, clinic.doctor_email)
        assert kinds(await notices(client))[0] == "appointment_cancelled"
