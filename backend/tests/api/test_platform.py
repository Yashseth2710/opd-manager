"""The platform: who can reach it, what it can see, and what it can stop.

The boundary is the point. A platform account reads clinics and counts and
never a patient, and nobody at a clinic reaches the platform at all.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_factory
from app.main import app
from app.models import Organization, OrganizationSubscription
from app.platform_admin import create
from tests.api.test_appointments import book, doctor_with_hours
from tests.api.test_clinic import set_up_clinic, sign_in, sign_up
from tests.api.test_consultations import a_clinic, become, my_email
from tests.api.test_doctors import add as add_doctor
from tests.api.test_documents import pdf, send
from tests.api.test_patients import register
from tests.api.test_payment_links import (  # noqa: F401
    a_bill,
    gateway,
    linked,
    opened_by_patient,
    token_from,
)
from tests.conftest import GOOD_PASSWORD, Outbox, registration, unique_email

API = "/api/v1"
AUTH = "/api/v1/auth"
PLATFORM = "/api/v1/platform"


@pytest.fixture
def ops_email() -> str:
    return unique_email("ops")


@pytest_asyncio.fixture
async def platform_admin(ops_email: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", GOOD_PASSWORD)
    await create(ops_email, "Asha", "Rao")
    return ops_email


@pytest_asyncio.fixture
async def elsewhere(client: AsyncClient) -> AsyncIterator[AsyncClient]:
    """A second browser, so one person can stay signed in while another acts."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as other:
        yield other


async def clinic_of(client: AsyncClient) -> str:
    me = (await client.get(f"{AUTH}/me")).json()["data"]
    found: str = me["organization"]["id"]
    return found


async def read(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{PLATFORM}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def suspend(client: AsyncClient, clinic: str, reason: str = "Unpaid for months") -> Any:
    response = await client.post(
        f"{PLATFORM}/organizations/{clinic}/suspend", json={"reason": reason}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def plan_id(client: AsyncClient, slug: str) -> str:
    listed = await read(client, "/plans")
    found: str = next(plan["id"] for plan in listed if plan["slug"] == slug)
    return found


async def put_on(client: AsyncClient, clinic: str, slug: str) -> Any:
    response = await client.put(
        f"{PLATFORM}/organizations/{clinic}/plan", json={"plan_id": await plan_id(client, slug)}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def limit(client: AsyncClient, slug: str, **limits: int | None) -> Any:
    plan = next(plan for plan in await read(client, "/plans") if plan["slug"] == slug)
    response = await client.patch(
        f"{PLATFORM}/plans/{plan['id']}", json={"limits": {**plan["limits"], **limits}}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def refused_by_plan(response: Any) -> str:
    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "PLAN_LIMIT_REACHED"
    message: str = error["message"]
    return message


class TestTheAccount:
    async def test_the_command_makes_an_account_that_belongs_to_no_clinic(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        session = await sign_in(client, platform_admin)

        assert session["organization"] is None
        assert session["role"] == "platform-admin"
        assert session["permissions"] == ["platform:manage"]

    async def test_the_command_refuses_an_address_a_clinic_already_uses(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await sign_up(client)
        monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", GOOD_PASSWORD)

        with pytest.raises(SystemExit, match="already has an account"):
            await create(await my_email(client), "Asha", "Rao")

    async def test_the_command_refuses_a_weak_password(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "short")

        with pytest.raises(SystemExit):
            await create(unique_email("ops"), "Asha", "Rao")


class TestTheBoundary:
    @pytest.mark.parametrize(
        "path",
        [
            "/patients",
            "/appointments",
            "/doctors",
            "/staff",
            "/clinic",
            "/audit-logs",
            "/search?q=rhea",
            "/dashboard/summary",
            "/reports/summary",
            "/notifications",
        ],
    )
    async def test_a_platform_account_reads_nothing_of_a_clinic(
        self, client: AsyncClient, platform_admin: str, path: str
    ) -> None:
        await sign_in(client, platform_admin)

        response = await client.get(f"{API}{path}")

        assert response.status_code == 403, (path, response.text)

    async def test_a_platform_account_writes_nothing_to_a_clinic(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        await sign_in(client, platform_admin)

        response = await client.post(
            f"{API}/patients",
            json={"first_name": "Rhea", "last_name": "Kapoor", "phone": "9820077441"},
        )

        assert response.status_code == 403

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/metrics"),
            ("GET", "/organizations"),
            ("GET", "/plans"),
            ("POST", f"/organizations/{uuid.uuid4()}/suspend"),
            ("PATCH", f"/plans/{uuid.uuid4()}"),
        ],
    )
    async def test_nobody_at_a_clinic_reaches_the_platform(
        self, client: AsyncClient, outbox: Outbox, method: str, path: str
    ) -> None:
        clinic = await a_clinic(client, outbox)

        for who in (clinic.admin, clinic.doctor_email):
            await become(client, who)
            response = await client.request(
                method, f"{PLATFORM}{path}", json={"reason": "Testing"}
            )
            assert response.status_code == 403, (who, response.text)

    async def test_signed_out_is_asked_to_sign_in(self, client: AsyncClient) -> None:
        response = await client.get(f"{PLATFORM}/organizations")

        assert response.status_code == 401

    async def test_the_clinic_list_carries_counts_and_never_a_patient(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        await sign_up(client, clinic_name="Harbour View Clinic")
        await register(client, first_name="Rhea", last_name="Kapoor", phone="9820077441")
        await become(client, platform_admin)

        response = await client.get(f"{PLATFORM}/organizations")
        [row] = response.json()["data"]["items"]
        detail = await client.get(f"{PLATFORM}/organizations/{row['id']}")

        assert row["name"] == "Harbour View Clinic"
        assert row["patients"] == 1
        for text in (response.text, detail.text):
            assert "Rhea" not in text
            assert "Kapoor" not in text
            assert "9820077441" not in text


class TestClinics:
    async def test_listed_newest_first_with_owner_plan_and_counts(
        self, client: AsyncClient, platform_admin: str, outbox: Outbox
    ) -> None:
        first = await sign_up(client, clinic_name="Older Clinic")
        await become(client, first["user"]["email"])
        second = await a_clinic(client, outbox)
        await register(client)
        await become(client, platform_admin)

        page = await read(client, "/organizations")

        assert [row["name"] for row in page["items"]] == [
            "Sunrise Family Clinic",
            "Older Clinic",
        ]
        newest = page["items"][0]
        assert newest["owner"]["email"] == second.admin
        assert newest["doctors"] == 1
        assert newest["staff"] == 2
        assert newest["patients"] == 1
        assert newest["standing"]["plan_name"] == "Group"
        assert newest["standing"]["on_trial"] is True
        assert page["total"] == 2
        assert page["statuses"] == {"all": 2, "pending": 2, "active": 0, "suspended": 0}

    async def test_found_by_name_or_owner_email_and_narrowed_by_status(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        owner = unique_email("meera")
        await sign_up(client, clinic_name="Lotus Eye Care", email=owner)
        await set_up_clinic(client)
        finished = await client.post(f"{API}/clinic/complete-setup")
        assert finished.status_code == 200, finished.text
        await sign_up(client, clinic_name="Banyan Children's Clinic")
        await become(client, platform_admin)

        by_name = await read(client, "/organizations", q="lotus")
        by_owner = await read(client, "/organizations", q=owner.split("@")[0])
        running = await read(client, "/organizations", status="active")
        wildcard = await read(client, "/organizations", q="%")

        assert [row["name"] for row in by_name["items"]] == ["Lotus Eye Care"]
        assert [row["name"] for row in by_owner["items"]] == ["Lotus Eye Care"]
        assert [row["name"] for row in running["items"]] == ["Lotus Eye Care"]
        assert wildcard["items"] == []

    async def test_one_clinic_shows_usage_against_its_plan(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        await sign_up(client)
        clinic = await clinic_of(client)
        await register(client)
        await become(client, platform_admin)
        await put_on(client, clinic, "starter")

        detail = await read(client, f"/organizations/{clinic}")

        assert detail["usage"]["patients"] == {"used": 1, "limit": 1000}
        assert detail["usage"]["doctors"] == {"used": 0, "limit": 2}
        assert detail["standing"]["on_trial"] is False
        assert [event["action"] for event in detail["history"]] == ["platform.plan_changed"]
        assert detail["history"][0]["changes"] == {"plan": ["Group (trial)", "Starter"]}

    async def test_a_clinic_that_does_not_exist_is_not_found(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        await sign_in(client, platform_admin)

        response = await client.get(f"{PLATFORM}/organizations/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PLATFORM_CLINIC_NOT_FOUND"

    async def test_the_numbers_across_every_clinic(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        await sign_up(client)
        await register(client)
        clinic = await clinic_of(client)
        await sign_up(client)
        await become(client, platform_admin)
        await suspend(client, clinic)

        numbers = await read(client, "/metrics")

        assert numbers["clinics"] == 2
        assert numbers["statuses"] == {"pending": 1, "active": 0, "suspended": 1}
        assert numbers["patients"] == 1
        assert numbers["accounts"] == 2
        assert numbers["new_clinics_this_month"] == 2
        assert numbers["on_trial"] == 2
        assert len(numbers["signups"]) == 12
        assert numbers["signups"][-1]["clinics"] == 2
        assert {plan["name"]: plan["clinics"] for plan in numbers["plans"]} == {
            "Starter": 0,
            "Clinic": 0,
            "Group": 2,
        }


class TestSuspension:
    async def test_stops_the_clinic_on_its_next_request(
        self, client: AsyncClient, elsewhere: AsyncClient, platform_admin: str
    ) -> None:
        admin = await sign_up(client)
        clinic = await clinic_of(client)
        await sign_in(elsewhere, platform_admin)

        await suspend(elsewhere, clinic)
        straight_away = await client.get(f"{API}/patients")
        renewed = await client.post(f"{AUTH}/refresh")
        again = await client.post(
            f"{AUTH}/login", json={"email": admin["user"]["email"], "password": GOOD_PASSWORD}
        )

        assert straight_away.status_code == 403
        assert straight_away.json()["error"]["code"] == "CLINIC_SUSPENDED"
        # Every session the clinic's people held was ended with it.
        assert renewed.status_code == 401
        assert again.status_code == 403
        assert again.json()["error"]["code"] == "CLINIC_SUSPENDED"

    async def test_leaves_every_other_clinic_alone(
        self, client: AsyncClient, elsewhere: AsyncClient, platform_admin: str
    ) -> None:
        await sign_up(client, clinic_name="Stopped Clinic")
        stopped = await clinic_of(client)
        await sign_up(client, clinic_name="Running Clinic")
        await sign_in(elsewhere, platform_admin)

        await suspend(elsewhere, stopped)

        assert (await client.get(f"{API}/patients")).status_code == 200

    async def test_needs_a_reason_and_happens_once(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        await sign_up(client)
        clinic = await clinic_of(client)
        await become(client, platform_admin)

        blank = await client.post(
            f"{PLATFORM}/organizations/{clinic}/suspend", json={"reason": "   "}
        )
        await suspend(client, clinic)
        twice = await client.post(
            f"{PLATFORM}/organizations/{clinic}/suspend", json={"reason": "Again"}
        )

        assert blank.status_code == 422
        assert twice.status_code == 422
        assert twice.json()["error"]["message"] == "This clinic is already suspended."

    async def test_reactivating_lets_them_back_to_where_they_were(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        admin = (await sign_up(client))["user"]["email"]
        await set_up_clinic(client)
        await client.post(f"{API}/clinic/complete-setup")
        clinic = await clinic_of(client)
        await become(client, platform_admin)
        await suspend(client, clinic)

        back = await client.post(f"{PLATFORM}/organizations/{clinic}/reactivate")
        not_twice = await client.post(f"{PLATFORM}/organizations/{clinic}/reactivate")
        await become(client, admin)

        assert back.json()["data"]["status"] == "active"
        assert not_twice.status_code == 422
        assert (await client.get(f"{API}/patients")).status_code == 200

    async def test_the_clinic_sees_it_in_its_own_log(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        admin = (await sign_up(client))["user"]["email"]
        clinic = await clinic_of(client)
        await become(client, platform_admin)
        await suspend(client, clinic, "Card declined twice")
        await client.post(f"{PLATFORM}/organizations/{clinic}/reactivate")
        await become(client, admin)

        log = (await client.get(f"{API}/audit-logs", params={"area": "clinic"})).json()["data"]

        assert [entry["action"] for entry in log["items"]] == [
            "platform.reactivated",
            "platform.suspended",
        ]
        assert log["items"][1]["actor_name"] == "Asha Rao (platform)"
        assert log["items"][1]["changes"]["reason"] == "Card declined twice"

    async def test_an_invitation_into_it_cannot_be_used(
        self, client: AsyncClient, platform_admin: str, outbox: Outbox
    ) -> None:
        await sign_up(client)
        clinic = await clinic_of(client)
        sent = await client.post(
            f"{API}/staff/invitations",
            json={
                "email": unique_email("late"),
                "first_name": "Late",
                "last_name": "Joiner",
                "role_slug": "receptionist",
            },
        )
        assert sent.status_code == 201, sent.text
        token = outbox.latest_token()
        await become(client, platform_admin)
        await suspend(client, clinic)

        opened = await client.get(f"{API}/invitations/{token}")
        accepted = await client.post(
            f"{API}/invitations/accept", json={"token": token, "password": GOOD_PASSWORD}
        )

        assert accepted.status_code == 403
        assert accepted.json()["error"]["code"] == "CLINIC_SUSPENDED"
        assert opened.status_code == 403


class TestPlans:
    async def test_a_new_clinic_tries_the_largest_plan_first(self, client: AsyncClient) -> None:
        await sign_up(client)

        plan = (await client.get(f"{API}/clinic/plan")).json()["data"]

        assert plan["name"] == "Group"
        assert plan["on_trial"] is True
        assert plan["after_trial_name"] == "Starter"
        assert plan["usage"]["staff"] == {"used": 1, "limit": None}

    async def test_only_the_clinic_admin_reads_the_plan(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        await become(client, clinic.doctor_email)

        assert (await client.get(f"{API}/clinic/plan")).status_code == 403

    async def test_a_full_plan_refuses_another_doctor(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        admin = (await sign_up(client))["user"]["email"]
        clinic = await clinic_of(client)
        await add_doctor(client, first_name="One")
        second = await add_doctor(client, first_name="Two")
        await become(client, platform_admin)
        await put_on(client, clinic, "starter")
        await become(client, admin)

        third = await client.post(
            f"{API}/doctors", json={"first_name": "Three", "last_name": "Iyer"}
        )
        message = refused_by_plan(third)
        await client.post(f"{API}/doctors/{second['id']}/deactivate")
        allowed = await client.post(
            f"{API}/doctors", json={"first_name": "Three", "last_name": "Iyer"}
        )
        brought_back = await client.post(f"{API}/doctors/{second['id']}/restore")

        assert message.startswith("The Starter plan allows 2 active doctors.")
        assert allowed.status_code == 201, allowed.text
        refused_by_plan(brought_back)

    async def test_a_lapsed_trial_falls_back_to_the_free_plan(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        clinic = uuid.UUID(await clinic_of(client))
        await add_doctor(client, first_name="One")
        await add_doctor(client, first_name="Two")
        await session.execute(
            update(OrganizationSubscription)
            .where(OrganizationSubscription.organization_id == clinic)
            .values(trial_ends_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
        )
        await session.commit()

        plan = (await client.get(f"{API}/clinic/plan")).json()["data"]
        third = await client.post(
            f"{API}/doctors", json={"first_name": "Three", "last_name": "Iyer"}
        )

        assert plan["name"] == "Starter"
        assert plan["trial_over"] is True
        refused_by_plan(third)

    async def test_patients_archived_make_room(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        admin = (await sign_up(client))["user"]["email"]
        clinic = await clinic_of(client)
        first = await register(client)
        await become(client, platform_admin)
        await put_on(client, clinic, "starter")
        await limit(client, "starter", max_patients=1)
        await become(client, admin)

        another = await client.post(
            f"{API}/patients",
            json={"first_name": "Omkar", "last_name": "Joshi", "phone": "9820055112"},
        )
        await client.post(f"{API}/patients/{first['id']}/archive")
        now_room = await client.post(
            f"{API}/patients",
            json={"first_name": "Omkar", "last_name": "Joshi", "phone": "9820055112"},
        )
        restoring = await client.post(f"{API}/patients/{first['id']}/restore")

        refused_by_plan(another)
        assert now_room.status_code == 201, now_room.text
        refused_by_plan(restoring)

    async def test_waiting_invitations_count_as_staff(
        self, client: AsyncClient, platform_admin: str, outbox: Outbox
    ) -> None:
        admin = (await sign_up(client))["user"]["email"]
        clinic = await clinic_of(client)
        await become(client, platform_admin)
        await put_on(client, clinic, "starter")
        await limit(client, "starter", max_staff=2)
        await become(client, admin)

        def invitation(name: str) -> dict[str, str]:
            return {
                "email": unique_email(name),
                "first_name": name,
                "last_name": "Person",
                "role_slug": "receptionist",
            }

        first = await client.post(f"{API}/staff/invitations", json=invitation("first"))
        second = await client.post(f"{API}/staff/invitations", json=invitation("second"))

        assert first.status_code == 201, first.text
        refused_by_plan(second)

    async def test_bookings_are_counted_by_the_month(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        admin = (await sign_up(client))["user"]["email"]
        clinic = await clinic_of(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        await become(client, platform_admin)
        await put_on(client, clinic, "starter")
        await limit(client, "starter", max_appointments_per_month=1)
        await become(client, admin)

        await book(client, patient, doctor)
        second = await client.post(
            f"{API}/appointments",
            json={
                "patient_id": patient["id"],
                "doctor_id": doctor["id"],
                "date": (dt.date.today() + dt.timedelta(days=2)).isoformat(),
                "start_time": "10:00",
            },
        )

        assert "bookings a month" in refused_by_plan(second)

    async def test_files_are_counted_by_size(
        self, client: AsyncClient, platform_admin: str, store: Any
    ) -> None:
        admin = (await sign_up(client))["user"]["email"]
        clinic = await clinic_of(client)
        patient = await register(client)
        await become(client, platform_admin)
        await put_on(client, clinic, "starter")
        await limit(client, "starter", max_storage_mb=1)
        await become(client, admin)

        small = await send(client, patient["id"], pdf())
        large = await send(client, patient["id"], pdf() + b"0" * (1024 * 1024))

        assert small.status_code == 201, small.text
        assert "MB of files" in refused_by_plan(large)
        assert store.puts == 1

    async def test_a_blank_limit_is_no_limit_and_zero_is_refused(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        await sign_in(client, platform_admin)

        opened = await limit(client, "starter", max_doctors=None)
        plan = next(plan for plan in await read(client, "/plans") if plan["slug"] == "starter")
        zero = await client.patch(
            f"{PLATFORM}/plans/{plan['id']}", json={"limits": {"max_doctors": 0}}
        )

        assert opened["limits"]["max_doctors"] is None
        assert zero.status_code == 422

    async def test_choosing_the_plan_a_clinic_already_has_is_refused(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        await sign_up(client)
        clinic = await clinic_of(client)
        await become(client, platform_admin)

        await put_on(client, clinic, "group")
        again = await client.put(
            f"{PLATFORM}/organizations/{clinic}/plan",
            json={"plan_id": await plan_id(client, "group")},
        )
        unknown = await client.put(
            f"{PLATFORM}/organizations/{clinic}/plan", json={"plan_id": str(uuid.uuid4())}
        )

        assert again.status_code == 422
        assert unknown.status_code == 422


class TestPaymentLinks:
    # The stand-in for Razorpay, brought in from the payment link tests.
    @pytest.mark.usefixtures("gateway")
    async def test_a_suspended_clinic_takes_no_new_money(
        self,
        client: AsyncClient,
        outbox: Outbox,
    ) -> None:
        bill = await a_bill(client, outbox)
        token = token_from((await linked(client, bill))["url"])
        clinic = uuid.UUID(await clinic_of(client))

        async def set_status(status: str) -> None:
            async with get_factory()() as apart:
                await apart.execute(
                    update(Organization).where(Organization.id == clinic).values(status=status)
                )
                await apart.commit()

        await set_status("suspended")
        stopped = (await opened_by_patient(client, token)).json()["data"]
        await set_status("active")
        back = (await opened_by_patient(client, token)).json()["data"]

        assert stopped["status"] == "cancelled"
        assert stopped["key_id"] is None
        assert stopped["order_id"] is None
        # Withdrawn for as long as the clinic is stopped, not closed for good.
        assert back["status"] == "open"
        assert back["order_id"] is not None


class TestOneAddressOneSide:
    async def test_a_clinic_cannot_be_registered_on_a_platform_address(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        body = registration(email=platform_admin)

        response = await client.post(f"{AUTH}/register", json=body)

        assert response.status_code == 409
        assert "cannot be used for a clinic account" in response.json()["error"]["message"]

    async def test_nobody_is_invited_on_a_platform_address(
        self, client: AsyncClient, platform_admin: str
    ) -> None:
        await sign_up(client)

        response = await client.post(
            f"{API}/staff/invitations",
            json={
                "email": platform_admin.upper(),
                "first_name": "Asha",
                "last_name": "Rao",
                "role_slug": "receptionist",
            },
        )

        assert response.status_code == 409
