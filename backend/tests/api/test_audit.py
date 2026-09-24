"""The audit log: what is written into it, who may read it, and that it holds."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEntry, Notification, User
from tests.api.test_appointments import book, booking
from tests.api.test_billing import a_desk, pay, raised
from tests.api.test_clinic import invite_and_accept, sign_up
from tests.api.test_consultations import a_clinic, become
from tests.api.test_patients import register
from tests.conftest import FakeRedis, Outbox

API = "/api/v1"
AUTH = "/api/v1/auth"


async def read_log(client: AsyncClient, **params: Any) -> Response:
    return await client.get(f"{API}/audit-logs", params=params)


async def the_log(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await read_log(client, **params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


def actions(found: dict[str, Any]) -> list[str]:
    return [entry["action"] for entry in found["items"]]


class TestWhatIsWritten:
    async def test_a_change_is_written_down_with_who_made_it(self, client: AsyncClient) -> None:
        await sign_up(client, first_name="Priya", last_name="Nair")
        patient = await register(client, first_name="Asha", last_name="Rao")

        entry = (await the_log(client))["items"][0]

        assert entry["action"] == "patient.registered"
        assert entry["actor_name"] == "Priya Nair"
        assert entry["resource_id"] == patient["id"]
        assert entry["resource_label"] == f"Asha Rao ({patient['patient_number']})"
        assert entry["ip_address"]

    async def test_an_edit_keeps_only_what_moved(self, client: AsyncClient) -> None:
        await sign_up(client)
        patient = await register(client, phone="9820011001")

        await client.patch(f"{API}/patients/{patient['id']}", json={"phone": "9820011999"})
        await client.patch(f"{API}/patients/{patient['id']}", json={"phone": "9820011999"})

        found = await the_log(client)
        assert actions(found) == ["patient.updated", "patient.registered"]
        assert found["items"][0]["changes"] == {"phone": ["9820011001", "9820011999"]}

    async def test_a_refused_change_leaves_nothing_behind(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        patient = await register(client)
        await book(client, patient, clinic.doctor)

        clash = await client.post(f"{API}/appointments", json=booking(patient, clinic.doctor))

        assert clash.status_code == 409
        assert actions(await the_log(client, area="appointments")) == ["appointment.booked"]

    async def test_a_payment_sent_twice_is_written_once(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        bill = await raised(client, patient, issue=True)

        for _ in range(2):
            response = await pay(client, bill, "50.00", key="same-payment")
            assert response.status_code == 201

        taken = [e for e in (await the_log(client))["items"] if e["action"] == "payment.taken"]
        assert len(taken) == 1
        assert taken[0]["changes"]["amount"] == "50.00"


class TestItHolds:
    async def test_the_database_refuses_to_change_it(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        await register(client)

        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(update(AuditEntry).values(actor_name="Somebody else"))
        await session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(delete(AuditEntry))
        await session.rollback()

        assert (await session.scalar(select(AuditEntry.actor_name))) != "Somebody else"

    async def test_it_goes_only_when_the_clinic_does(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        await register(client)
        clinic_id = (await client.get(f"{API}/clinic")).json()["data"]["id"]

        await session.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": clinic_id}
        )
        await session.commit()

        assert await session.scalar(select(AuditEntry.id)) is None


class TestWhoReadsIt:
    @pytest.mark.parametrize("role", ["receptionist", "doctor", "staff"])
    async def test_only_the_clinic_admin(
        self, client: AsyncClient, outbox: Outbox, role: str
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role=role, outbox=outbox)
        await become(client, address)

        assert (await read_log(client)).status_code == 403

    async def test_another_clinic_sees_none_of_it(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client, first_name="Meera")
        await client.post(f"{AUTH}/logout")

        await sign_up(client, clinic_name="Harbour Clinic")
        found = await the_log(client)

        assert found["total"] == 0
        assert found["actors"] == []

    async def test_nobody_signed_out(self, client: AsyncClient) -> None:
        assert (await read_log(client)).status_code == 401


class TestNarrowingIt:
    async def test_by_area_record_person_and_words(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient = await a_desk(client, outbox)
        await raised(client, patient, issue=True)
        other = await register(client, first_name="Kabir", last_name="Shah", phone="9820044556")
        me = (await client.get(f"{AUTH}/me")).json()["data"]["user"]["id"]

        assert set(actions(await the_log(client, area="billing"))) == {"invoice.raised"}
        about = await the_log(client, resource_id=other["id"])
        assert actions(about) == ["patient.registered"]
        assert (await the_log(client, q="kabir"))["total"] == 1
        mine = await the_log(client, actor_id=me)
        assert {entry["actor_id"] for entry in mine["items"]} == {me}
        # The doctor joining was written down as the doctor's own doing.
        assert mine["total"] < (await the_log(client))["total"]
        assert me in [actor["id"] for actor in mine["actors"]]

    async def test_by_dates_at_the_clinic(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client)
        today = (await the_log(client))["items"][0]["created_at"][:10]

        assert (await the_log(client, **{"from": "2020-01-01", "to": "2020-01-31"}))[
            "total"
        ] == 0
        backwards = await read_log(client, **{"from": today, "to": "2020-01-01"})
        assert backwards.status_code == 422

    async def test_a_like_pattern_matches_only_itself(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client, first_name="Asha")

        assert (await the_log(client, q="%"))["total"] == 0


class TestSigningIn:
    async def test_wrong_passwords_are_written_down_and_a_lock_tells_them(
        self,
        client: AsyncClient,
        outbox: Outbox,
        session: AsyncSession,
        fake_redis: FakeRedis,
    ) -> None:
        await sign_up(client)
        admin = (await client.get(f"{AUTH}/me")).json()["data"]["user"]["email"]
        address = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await client.post(f"{AUTH}/logout")

        for _ in range(5):
            wrong = await client.post(
                f"{AUTH}/login", json={"email": address, "password": "not it at all"}
            )
            assert wrong.status_code in (401, 423)

        await become(client, admin)
        found = await the_log(client, area="sign_in")
        assert actions(found) == ["signin.locked"] + ["signin.failed"] * 4
        assert found["items"][0]["actor_id"] is None

        person = (await session.execute(select(User).where(User.email == address))).scalar_one()
        assert person.locked_until is not None
        told = (
            await session.execute(select(Notification).where(Notification.user_id == person.id))
        ).scalar_one()
        assert told.kind == "account_locked"

    async def test_an_address_nobody_has_writes_nothing(self, client: AsyncClient) -> None:
        await sign_up(client)
        await client.post(
            f"{AUTH}/login",
            json={"email": f"nobody.{uuid.uuid4().hex[:8]}@example.org", "password": "x" * 12},
        )

        assert (await the_log(client, area="sign_in"))["total"] == 0
