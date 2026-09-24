"""The search box: what it finds, for whom, and never from another clinic."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.api.test_appointments import act, book
from tests.api.test_billing import raised
from tests.api.test_clinic import invite_and_accept, sign_up
from tests.api.test_consultations import a_clinic, become, linked_doctor
from tests.api.test_patients import register
from tests.conftest import Outbox

API = "/api/v1"


async def search(client: AsyncClient, typed: str) -> dict[str, Any]:
    response = await client.get(f"{API}/search", params={"q": typed})
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


def names(found: dict[str, Any], kind: str) -> list[str]:
    key = {
        "patients": "full_name",
        "appointments": "patient_name",
        "bills": "patient_name",
        "doctors": "display_name",
        "staff": "full_name",
    }[kind]
    return [row[key] for row in found[kind]]


class TestFinding:
    async def test_a_patient_by_a_misspelt_name_with_their_bookings_and_bills(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        rhea = await register(client, first_name="Rhea", last_name="Kapoor", phone="9820077441")
        await register(client, first_name="Omkar", last_name="Joshi", phone="9820055112")
        made = await book(client, rhea, clinic.doctor)
        bill = await raised(client, rhea)

        found = await search(client, "Kapor")

        assert names(found, "patients") == ["Rhea Kapoor"]
        assert [row["id"] for row in found["appointments"]] == [made["id"]]
        assert found["appointments"][0]["doctor_name"] == clinic.doctor["display_name"]
        assert [row["id"] for row in found["bills"]] == [bill["id"]]

    async def test_by_patient_number_phone_and_bill_number(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        rhea = await register(client, first_name="Rhea", last_name="Kapoor", phone="9820077441")
        bill = await raised(client, rhea)
        issued = await client.post(f"{API}/invoices/{bill['id']}/issue")
        assert issued.status_code == 200, issued.text
        number = issued.json()["data"]["invoice_number"]

        by_patient = await search(client, rhea["patient_number"])
        assert names(by_patient, "patients") == ["Rhea Kapoor"]
        assert names(await search(client, "98200 77441"), "patients") == ["Rhea Kapoor"]
        by_number = await search(client, number)
        assert [row["invoice_number"] for row in by_number["bills"]] == [number]

    async def test_doctors_and_colleagues_by_name(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)

        found = await search(client, "Ananya")
        assert names(found, "doctors") == [clinic.doctor["display_name"]]
        assert found["doctors"][0]["active"] is True

        # The profile is Ananya; the account behind it goes by its own name.
        [colleague] = (await search(client, clinic.doctor_email.split("@")[0]))["staff"]
        assert colleague["email"] == clinic.doctor_email
        assert colleague["role"] == "Doctor"

    async def test_an_archived_patient_is_found_and_says_so(self, client: AsyncClient) -> None:
        await sign_up(client)
        patient = await register(client, first_name="Leela", last_name="Menon")
        archived = await client.post(f"{API}/patients/{patient['id']}/archive")
        assert archived.status_code == 200, archived.text

        [found] = (await search(client, "Leela"))["patients"]

        assert found["archived"] is True

    async def test_only_bookings_still_ahead(self, client: AsyncClient, outbox: Outbox) -> None:
        clinic = await a_clinic(client, outbox)
        rhea = await register(client, first_name="Rhea", last_name="Kapoor", phone="9820077441")
        kept = await book(client, rhea, clinic.doctor, start_time="09:00")
        dropped = await book(client, rhea, clinic.doctor, start_time="09:30")
        cancelled = await act(client, dropped["id"], "cancel", reason="Feeling better")
        assert cancelled.status_code == 200, cancelled.text

        found = await search(client, "Rhea")

        assert [row["id"] for row in found["appointments"]] == [kept["id"]]


class TestWhoSeesWhat:
    async def test_the_desk_searches_everything_but_colleagues(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        desk = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, desk)

        found = await search(client, "anyone")

        assert found["searched"] == ["patients", "appointments", "bills", "doctors"]
        assert found["staff"] == []

    async def test_a_doctor_finds_only_their_own_bookings_and_no_bills(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        _, other = await linked_doctor(client, outbox, first_name="Rohan")
        rhea = await register(client, first_name="Rhea", last_name="Kapoor", phone="9820077441")
        mine = await book(client, rhea, clinic.doctor, start_time="09:00")
        await book(client, rhea, other, start_time="10:00")
        await raised(client, rhea)

        await become(client, clinic.doctor_email)
        found = await search(client, "Rhea")

        assert found["searched"] == ["patients", "appointments", "doctors"]
        assert names(found, "patients") == ["Rhea Kapoor"]
        assert [row["id"] for row in found["appointments"]] == [mine["id"]]
        assert found["bills"] == []
        assert found["staff"] == []

    async def test_the_staff_role_finds_people_but_not_money(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        helper = await invite_and_accept(client, role="staff", outbox=outbox)
        await become(client, helper)

        assert (await search(client, "anyone"))["searched"] == [
            "patients",
            "appointments",
            "doctors",
        ]

    async def test_another_clinic_is_never_searched(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        rhea = await register(client, first_name="Rhea", last_name="Kapoor", phone="9820077441")
        await book(client, rhea, clinic.doctor)
        await raised(client, rhea)

        await sign_up(client)
        found = await search(client, "Rhea")
        doctors = await search(client, "Ananya")

        assert found["patients"] == found["appointments"] == found["bills"] == []
        assert doctors["doctors"] == doctors["staff"] == []

    async def test_signed_out_is_refused(self, client: AsyncClient) -> None:
        response = await client.get(f"{API}/search", params={"q": "Rhea"})

        assert response.status_code == 401


class TestWhatIsTyped:
    async def test_one_letter_or_a_bare_wildcard_finds_nothing(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        await register(client, first_name="Rhea", last_name="Kapoor", phone="9820077441")

        for typed in ("r", "  r  ", "%%", "__", ""):
            found = await search(client, typed)
            assert found["patients"] == [], typed
            assert found["bills"] == [], typed

    async def test_spaces_inside_are_squeezed(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client, first_name="Rhea", last_name="Kapoor", phone="9820077441")

        found = await search(client, "  rhea    kapoor ")

        assert found["query"] == "rhea kapoor"
        assert names(found, "patients") == ["Rhea Kapoor"]

    async def test_a_very_long_term_is_refused(self, client: AsyncClient) -> None:
        await sign_up(client)

        response = await client.get(f"{API}/search", params={"q": "x" * 101})

        assert response.status_code == 422
