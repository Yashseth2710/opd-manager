"""Vital signs: taken for a place in the queue, corrected on the day, and
read wherever the patient is looked at."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vitals
from tests.api.test_appointments import doctor_with_hours
from tests.api.test_clinic import AUTH, invite_and_accept, sign_in, sign_up
from tests.api.test_consultations import a_clinic, become, finished, opened, saved
from tests.api.test_patients import register
from tests.api.test_queue import lane_of, refusal, stepped, the_queue, walked_in
from tests.conftest import Outbox

API = "/api/v1"

FULL = {
    "systolic_mmhg": 150,
    "diastolic_mmhg": 95,
    "pulse_bpm": 88,
    "temperature_c": "37.06",
    "spo2_percent": 97,
    "respiratory_rate": 16,
    "weight_kg": "72.5",
    "height_cm": "165",
    "glucose_mg_dl": 180,
    "glucose_timing": "random",
    "note": "  Left arm, sitting.  ",
}


async def take(client: AsyncClient, entry_id: str, **readings: Any) -> Response:
    return await client.post(f"{API}/vitals", json={"queue_entry_id": entry_id, **readings})


async def taken(client: AsyncClient, entry_id: str, **readings: Any) -> dict[str, Any]:
    response = await take(client, entry_id, **readings)
    assert response.status_code == 201, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def correct(client: AsyncClient, vitals_id: str, **readings: Any) -> Response:
    return await client.put(f"{API}/vitals/{vitals_id}", json=readings)


async def of_patient(client: AsyncClient, patient_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/vitals", params={"patient_id": patient_id})
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def waiting(client: AsyncClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A clinic with a doctor and one patient waiting to see them. The admin
    is signed in."""
    await sign_up(client)
    doctor = await doctor_with_hours(client)
    patient = await register(client)
    return doctor, patient, await walked_in(client, patient, doctor)


def queued(queue: dict[str, Any], doctor: dict[str, Any], entry_id: str) -> dict[str, Any]:
    lane = lane_of(queue, doctor)
    places = [*lane["waiting"], *lane["done"], lane["now_seeing"], lane["called"]]
    return next(place for place in places if place and place["id"] == entry_id)


class TestTaking:
    async def test_a_full_set_for_somebody_waiting(self, client: AsyncClient) -> None:
        doctor, patient, entry = await waiting(client)

        found = await taken(client, entry["id"], **FULL)

        assert found["patient_id"] == patient["id"]
        assert found["queue_entry_id"] == entry["id"]
        assert (found["systolic_mmhg"], found["diastolic_mmhg"]) == (150, 95)
        assert found["temperature_c"] == 37.06
        assert found["weight_kg"] == 72.5
        assert found["height_cm"] == 165
        assert found["note"] == "Left arm, sitting."
        # The patient was born in 1988, so the adult ranges apply.
        assert found["bmi"] == 26.6
        assert found["bmi_band"] == "obese"
        assert found["flags"] == {"blood_pressure": "high", "bmi": "high"}
        assert found["taken_by"]
        assert found["changed_by"] is None
        assert found["can_change"] is True

        # The desk sees them on the patient's place in the line.
        brief = queued(await the_queue(client), doctor, entry["id"])["vitals"]
        assert brief["id"] == found["id"]
        assert (brief["systolic_mmhg"], brief["diastolic_mmhg"]) == (150, 95)
        assert brief["flags"] == {"blood_pressure": "high", "bmi": "high"}

    async def test_one_reading_is_enough(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        found = await taken(client, entry["id"], weight_kg="61")
        assert found["weight_kg"] == 61
        assert found["systolic_mmhg"] is None
        assert found["bmi"] is None
        assert found["flags"] == {}

    async def test_a_fahrenheit_reading_survives_the_trip(self, client: AsyncClient) -> None:
        # 98.7 °F is 37.0556 °C. Kept to two places it converts back to 98.7,
        # where one place would have come back as 98.8.
        _, _, entry = await waiting(client)
        found = await taken(client, entry["id"], temperature_c="37.0556")
        assert found["temperature_c"] == 37.06
        assert round(found["temperature_c"] * 9 / 5 + 32, 1) == 98.7

    async def test_one_set_per_visit(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        await taken(client, entry["id"], pulse_bpm=80)

        again = refusal(await take(client, entry["id"], pulse_bpm=82))

        assert again["status"] == 409
        assert again["code"] == "VITALS_ALREADY_TAKEN"

    async def test_two_desks_at_once_leave_one_set(self, client: AsyncClient) -> None:
        _, patient, entry = await waiting(client)

        answers = await asyncio.gather(
            take(client, entry["id"], pulse_bpm=80), take(client, entry["id"], pulse_bpm=90)
        )

        assert sorted(answer.status_code for answer in answers) == [201, 409]
        assert (await of_patient(client, patient["id"]))["total"] == 1

    async def test_the_doctor_can_take_them_in_the_room(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        patient = await register(client)
        entry = await walked_in(client, patient, clinic.doctor)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)

        found = await taken(client, entry["id"], spo2_percent=91)

        assert found["flags"] == {"spo2": "low"}
        assert found["can_change"] is True


class TestWhatIsRefused:
    async def test_nothing_measured(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        for empty in ({}, {"note": "Patient refused"}, {"glucose_timing": "fasting"}):
            refused = refusal(await take(client, entry["id"], **empty))
            assert refused["status"] == 422
            assert refused["fields"] == {"readings": "Enter at least one reading."}

    async def test_half_a_blood_pressure(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        refused = refusal(await take(client, entry["id"], systolic_mmhg=120))
        assert refused["fields"] == {"diastolic_mmhg": "Enter the lower number as well."}
        refused = refusal(await take(client, entry["id"], diastolic_mmhg=80))
        assert refused["fields"] == {"systolic_mmhg": "Enter the upper number as well."}

    async def test_the_numbers_of_a_pressure_the_wrong_way_round(
        self, client: AsyncClient
    ) -> None:
        _, _, entry = await waiting(client)
        refused = refusal(await take(client, entry["id"], systolic_mmhg=80, diastolic_mmhg=120))
        assert refused["fields"] == {
            "diastolic_mmhg": "The lower number has to be below the upper one."
        }
        refused = refusal(await take(client, entry["id"], systolic_mmhg=90, diastolic_mmhg=90))
        assert "diastolic_mmhg" in refused["fields"]

    async def test_a_sugar_needs_to_say_when(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        refused = refusal(await take(client, entry["id"], glucose_mg_dl=110))
        assert refused["fields"] == {"glucose_timing": "Say when the sugar was taken."}
        refused = refusal(
            await take(client, entry["id"], glucose_mg_dl=110, glucose_timing="lunchtime")
        )
        assert refused["fields"] == {"glucose_timing": "Pick one of the options."}

    async def test_a_when_without_a_sugar_is_dropped(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        found = await taken(client, entry["id"], pulse_bpm=72, glucose_timing="fasting")
        assert found["glucose_timing"] is None

    async def test_slips_of_the_finger(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        cases = {
            "systolic_mmhg": (1200, "Has to be 300 or less."),
            "pulse_bpm": (8, "Has to be 20 or more."),
            "temperature_c": ("98.6", "Has to be 45 or less."),
            "spo2_percent": (101, "Has to be 100 or less."),
            "weight_kg": ("0", "Has to be 0.3 or more."),
            "height_cm": ("1650", "Has to be 250 or less."),
            "glucose_mg_dl": (5, "Has to be 10 or more."),
            "respiratory_rate": (120, "Has to be 80 or less."),
        }
        for column, (value, message) in cases.items():
            refused = refusal(await take(client, entry["id"], **{column: value}))
            assert refused["status"] == 422, column
            assert refused["fields"] == {column: message}, column

    async def test_readings_that_are_not_numbers(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        refused = refusal(await take(client, entry["id"], pulse_bpm="fast"))
        assert refused["fields"] == {"pulse_bpm": "That has to be a whole number."}
        refused = refusal(await take(client, entry["id"], pulse_bpm=72.5))
        assert refused["fields"] == {"pulse_bpm": "That has to be a whole number."}
        refused = refusal(await take(client, entry["id"], pulse_bpm=72, taken_by_id="x"))
        assert refused["fields"] == {"taken_by_id": "This is not something you can set here."}

    async def test_a_long_note(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        refused = refusal(await take(client, entry["id"], pulse_bpm=72, note="x" * 201))
        assert refused["fields"] == {"note": "Keep this to 200 characters."}

    async def test_somebody_not_in_the_queue(self, client: AsyncClient) -> None:
        await waiting(client)
        refused = refusal(await take(client, str(uuid.uuid4()), pulse_bpm=72))
        assert refused["status"] == 422
        assert refused["fields"] == {"queue_entry_id": "That patient is not in the queue."}

    async def test_after_the_visit_is_over(self, client: AsyncClient) -> None:
        _, _, seen = await waiting(client)
        await stepped(client, seen["id"], "start")
        await stepped(client, seen["id"], "complete")
        refused = refusal(await take(client, seen["id"], pulse_bpm=72))
        assert (refused["status"], refused["code"]) == (409, "VITALS_LOCKED")
        assert refused["message"] == "They have already been seen, so the visit is closed."

    async def test_somebody_marked_as_gone(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        await stepped(client, entry["id"], "no-show")
        refused = refusal(await take(client, entry["id"], pulse_bpm=72))
        assert (refused["status"], refused["code"]) == (409, "VITALS_LOCKED")

    async def test_a_place_from_another_day(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        from app.models import QueueEntry

        _, _, entry = await waiting(client)
        await session.execute(
            update(QueueEntry)
            .where(QueueEntry.id == uuid.UUID(entry["id"]))
            .values(token_date=QueueEntry.token_date - dt.timedelta(days=1))
        )
        await session.commit()

        refused = refusal(await take(client, entry["id"], pulse_bpm=72))

        assert (refused["status"], refused["code"]) == (409, "VITALS_LOCKED")
        assert refused["message"].startswith("This place was in the queue on ")


class TestCorrecting:
    async def test_a_correction_replaces_the_whole_set(self, client: AsyncClient) -> None:
        doctor, _, entry = await waiting(client)
        first = await taken(client, entry["id"], **FULL)

        response = await correct(client, first["id"], systolic_mmhg=130, diastolic_mmhg=85)

        assert response.status_code == 200, response.text
        found = response.json()["data"]
        assert (found["systolic_mmhg"], found["diastolic_mmhg"]) == (130, 85)
        # Everything not sent is taken as not measured.
        assert found["pulse_bpm"] is None
        assert found["glucose_timing"] is None
        assert found["note"] is None
        assert found["flags"] == {}
        assert found["changed_by"] == found["taken_by"]
        assert found["taken_at"] == first["taken_at"]
        brief = queued(await the_queue(client), doctor, entry["id"])["vitals"]
        assert brief["systolic_mmhg"] == 130
        assert brief["pulse_bpm"] is None

    async def test_somebody_else_at_the_desk_can_put_it_right(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, entry = await waiting(client)
        first = await taken(client, entry["id"], pulse_bpm=72)
        desk = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, desk)

        found = (await correct(client, first["id"], pulse_bpm=76)).json()["data"]

        assert found["pulse_bpm"] == 76
        assert found["changed_by"] == "Joiner Person"
        assert found["taken_by"] != found["changed_by"]

    async def test_a_correction_is_checked_like_the_first(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        first = await taken(client, entry["id"], pulse_bpm=72)
        refused = refusal(await correct(client, first["id"]))
        assert refused["fields"] == {"readings": "Enter at least one reading."}
        refused = refusal(await correct(client, first["id"], systolic_mmhg=120))
        assert "diastolic_mmhg" in refused["fields"]

    async def test_once_the_visit_is_finished_they_stay(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        patient = await register(client)
        entry = await walked_in(client, patient, clinic.doctor)
        first = await taken(client, entry["id"], pulse_bpm=72)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)
        notes = await saved(client, await opened(client, entry["id"]), chief_complaint="Cough")
        await finished(client, notes)

        refused = refusal(await correct(client, first["id"], pulse_bpm=74))
        assert (refused["status"], refused["code"]) == (409, "VITALS_LOCKED")
        assert refused["message"].startswith("The visit is finished")
        refused = refusal(await client.delete(f"{API}/vitals/{first['id']}"))
        assert refused["code"] == "VITALS_LOCKED"

        found = (await client.get(f"{API}/vitals/{first['id']}")).json()["data"]
        assert found["can_change"] is False
        assert found["pulse_bpm"] == 72

    async def test_the_day_after_they_stay(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        _, _, entry = await waiting(client)
        first = await taken(client, entry["id"], pulse_bpm=72)
        await session.execute(
            update(Vitals)
            .where(Vitals.id == uuid.UUID(first["id"]))
            .values(taken_on=Vitals.taken_on - dt.timedelta(days=1))
        )
        await session.commit()

        refused = refusal(await correct(client, first["id"], pulse_bpm=74))

        assert (refused["status"], refused["code"]) == (409, "VITALS_LOCKED")
        assert "can only be changed on the day" in refused["message"]
        found = (await client.get(f"{API}/vitals/{first['id']}")).json()["data"]
        assert found["can_change"] is False


class TestTakingThemBack:
    async def test_a_set_taken_for_the_wrong_person(self, client: AsyncClient) -> None:
        doctor, patient, entry = await waiting(client)
        first = await taken(client, entry["id"], pulse_bpm=72)

        response = await client.delete(f"{API}/vitals/{first['id']}")

        assert response.status_code == 200, response.text
        assert queued(await the_queue(client), doctor, entry["id"])["vitals"] is None
        assert (await of_patient(client, patient["id"]))["total"] == 0
        # And they can be taken again, for the right person this time.
        await taken(client, entry["id"], pulse_bpm=80)

    async def test_undoing_the_check_in_takes_them_with_it(self, client: AsyncClient) -> None:
        _, patient, entry = await waiting(client)
        first = await taken(client, entry["id"], pulse_bpm=72)

        assert (await client.delete(f"{API}/queue/{entry['id']}")).status_code == 200

        assert (await of_patient(client, patient["id"]))["total"] == 0
        gone = refusal(await client.get(f"{API}/vitals/{first['id']}"))
        assert (gone["status"], gone["code"]) == (404, "VITALS_NOT_FOUND")


class TestReading:
    async def test_a_patients_readings_newest_first(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        doctor, patient, first_visit = await waiting(client)
        older = await taken(client, first_visit["id"], weight_kg="80")
        await stepped(client, first_visit["id"], "start")
        await stepped(client, first_visit["id"], "complete")
        await session.execute(
            update(Vitals)
            .where(Vitals.id == uuid.UUID(older["id"]))
            .values(taken_at=Vitals.taken_at - dt.timedelta(days=30))
        )
        await session.commit()
        second_visit = await walked_in(client, patient, doctor)
        newer = await taken(client, second_visit["id"], weight_kg="77.5")
        someone_else = await register(client, first_name="Rohan", phone="9820099887")
        await taken(client, (await walked_in(client, someone_else, doctor))["id"], pulse_bpm=70)

        page = await of_patient(client, patient["id"])

        assert page["total"] == 2
        assert [item["id"] for item in page["items"]] == [newer["id"], older["id"]]
        assert [item["can_change"] for item in page["items"]] == [True, False]
        paged = await client.get(
            f"{API}/vitals", params={"patient_id": patient["id"], "limit": 1, "offset": 1}
        )
        assert [item["id"] for item in paged.json()["data"]["items"]] == [older["id"]]

    async def test_the_set_for_one_visit(self, client: AsyncClient) -> None:
        _, _, entry = await waiting(client)
        params = {"queue_entry_id": entry["id"]}
        none_yet = (await client.get(f"{API}/vitals", params=params)).json()["data"]
        assert none_yet == {"items": [], "total": 0}

        found = await taken(client, entry["id"], pulse_bpm=72)

        page = (await client.get(f"{API}/vitals", params=params)).json()["data"]
        assert [item["id"] for item in page["items"]] == [found["id"]]

    async def test_a_listing_has_to_say_whose(self, client: AsyncClient) -> None:
        await waiting(client)
        refused = refusal(await client.get(f"{API}/vitals"))
        assert refused["status"] == 422
        assert refused["fields"] == {"patient_id": "Say whose vital signs to show."}


class TestWhoSeesWhat:
    async def test_a_doctor_takes_them_only_for_their_own_patients(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        colleague = await doctor_with_hours(client, first_name="Farhan")
        patient = await register(client)
        theirs = await walked_in(client, patient, colleague)
        by_desk = await taken(client, theirs["id"], pulse_bpm=72)
        await become(client, clinic.doctor_email)

        refused = refusal(await take(client, theirs["id"], pulse_bpm=72))
        assert refused["fields"] == {"queue_entry_id": "That patient is not in the queue."}
        refused = refusal(await correct(client, by_desk["id"], pulse_bpm=74))
        assert (refused["status"], refused["code"]) == (404, "VITALS_NOT_FOUND")

        # Reading them is another matter: the patient's record is open to
        # every doctor at the clinic, and so are their readings.
        found = (await client.get(f"{API}/vitals/{by_desk['id']}")).json()["data"]
        assert found["pulse_bpm"] == 72
        assert found["can_change"] is False

    async def test_read_only_staff_can_read_but_not_take(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, patient, entry = await waiting(client)
        found = await taken(client, entry["id"], pulse_bpm=72)
        staff = await invite_and_accept(client, role="staff", outbox=outbox)
        await become(client, staff)

        assert (await of_patient(client, patient["id"]))["items"][0]["can_change"] is False
        for refused in (
            await take(client, entry["id"], pulse_bpm=72),
            await correct(client, found["id"], pulse_bpm=72),
            await client.delete(f"{API}/vitals/{found['id']}"),
        ):
            assert refusal(refused)["status"] == 403

    async def test_every_role_is_given_what_it_needs(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        admin = (await client.get(f"{AUTH}/me")).json()["data"]
        assert {"vitals:record", "vitals:read"} <= set(admin["permissions"])
        for role, record in (("doctor", True), ("receptionist", True), ("staff", False)):
            address = await invite_and_accept(client, role=role, outbox=outbox)
            await client.post(f"{AUTH}/logout")
            await sign_in(client, address)
            granted = set((await client.get(f"{AUTH}/me")).json()["data"]["permissions"])
            assert "vitals:read" in granted, role
            assert ("vitals:record" in granted) is record, role
            await client.post(f"{AUTH}/logout")
            await sign_in(client, admin["user"]["email"])

    async def test_another_clinic_finds_nothing(self, client: AsyncClient) -> None:
        _, patient, entry = await waiting(client)
        found = await taken(client, entry["id"], pulse_bpm=72)

        await client.post(f"{AUTH}/logout")
        await sign_up(client)

        for response in (
            await client.get(f"{API}/vitals/{found['id']}"),
            await correct(client, found["id"], pulse_bpm=74),
            await client.delete(f"{API}/vitals/{found['id']}"),
        ):
            assert refusal(response)["status"] == 404
        assert (await of_patient(client, patient["id"])) == {"items": [], "total": 0}
        refused = refusal(await take(client, entry["id"], pulse_bpm=72))
        assert refused["fields"] == {"queue_entry_id": "That patient is not in the queue."}
        by_visit = await client.get(f"{API}/vitals", params={"queue_entry_id": entry["id"]})
        assert by_visit.json()["data"] == {"items": [], "total": 0}

    async def test_signed_out(self, client: AsyncClient) -> None:
        for response in (
            await client.get(f"{API}/vitals", params={"patient_id": str(uuid.uuid4())}),
            await client.post(f"{API}/vitals", json={}),
            await client.get(f"{API}/vitals/{uuid.uuid4()}"),
        ):
            assert response.status_code == 401

    async def test_a_malformed_id(self, client: AsyncClient) -> None:
        await waiting(client)
        refused = refusal(await client.get(f"{API}/vitals/not-an-id"))
        assert refused["status"] == 422
