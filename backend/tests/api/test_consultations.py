"""Consultation notes: opening them in the room, writing, finishing, adding.

Most of these run as a doctor whose account is linked to a profile, because
notes are theirs to write. The clinic admin sets the day up first and reads
the result afterwards.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.test_appointments import doctor_with_hours, someone
from tests.api.test_clinic import invite_and_accept, sign_in, sign_up
from tests.api.test_patients import register
from tests.api.test_queue import (
    appointment,
    booked_today,
    checked_in,
    lane_of,
    refusal,
    step,
    stepped,
    the_queue,
    today,
    walked_in,
)
from tests.conftest import Outbox

API = "/api/v1"
AUTH = "/api/v1/auth"


@dataclass(frozen=True)
class Clinic:
    admin: str
    doctor_email: str
    doctor: dict[str, Any]


async def my_email(client: AsyncClient) -> str:
    email: str = (await client.get(f"{AUTH}/me")).json()["data"]["user"]["email"]
    return email


async def become(client: AsyncClient, email: str) -> None:
    await client.post(f"{AUTH}/logout")
    await sign_in(client, email)


async def member_id(client: AsyncClient, email: str) -> str:
    listing = (await client.get(f"{API}/staff")).json()["data"]
    found: str = next(member["id"] for member in listing if member["email"] == email)
    return found


async def linked_doctor(
    client: AsyncClient, outbox: Outbox, **details: Any
) -> tuple[str, dict[str, Any]]:
    """A doctor's account with a profile linked to it. The admin stays
    signed in."""
    address = await invite_and_accept(client, role="doctor", outbox=outbox)
    doctor = await doctor_with_hours(
        client, user_id=await member_id(client, address), **details
    )
    return address, doctor


async def a_clinic(client: AsyncClient, outbox: Outbox) -> Clinic:
    await sign_up(client)
    admin = await my_email(client)
    address, doctor = await linked_doctor(client, outbox, first_name="Ananya")
    return Clinic(admin=admin, doctor_email=address, doctor=doctor)


async def in_the_room(
    client: AsyncClient, patient: dict[str, Any], doctor: dict[str, Any], **walk: Any
) -> dict[str, Any]:
    entry = await walked_in(client, patient, doctor, **walk)
    return await stepped(client, entry["id"], "start")


async def open_notes(client: AsyncClient, entry_id: str) -> Response:
    return await client.post(f"{API}/consultations", json={"queue_entry_id": entry_id})


async def opened(client: AsyncClient, entry_id: str) -> dict[str, Any]:
    response = await open_notes(client, entry_id)
    assert response.status_code in (200, 201), response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def save(client: AsyncClient, notes: dict[str, Any], **fields: Any) -> Response:
    return await client.patch(
        f"{API}/consultations/{notes['id']}",
        json={"version": fields.pop("version", notes["version"]), **fields},
    )


async def saved(client: AsyncClient, notes: dict[str, Any], **fields: Any) -> dict[str, Any]:
    response = await save(client, notes, **fields)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def finish(client: AsyncClient, notes: dict[str, Any], **body: Any) -> Response:
    return await client.post(
        f"{API}/consultations/{notes['id']}/complete",
        json={"version": notes["version"], **body},
    )


async def finished(client: AsyncClient, notes: dict[str, Any]) -> dict[str, Any]:
    response = await finish(client, notes)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def add_addendum(client: AsyncClient, notes: dict[str, Any], body: str) -> Response:
    return await client.post(f"{API}/consultations/{notes['id']}/addenda", json={"body": body})


async def read(client: AsyncClient, consultation_id: str) -> Response:
    return await client.get(f"{API}/consultations/{consultation_id}")


async def listing(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/consultations", params=params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


class TestOpening:
    async def test_the_doctor_opens_notes_for_the_patient_in_the_room(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        asha = await someone(client, "Asha")
        entry = await in_the_room(client, asha, clinic.doctor, reason="Cough for a week")
        await become(client, clinic.doctor_email)

        response = await open_notes(client, entry["id"])

        assert response.status_code == 201, response.text
        notes = response.json()["data"]
        assert notes["status"] == "draft"
        assert notes["version"] == 1
        assert notes["patient"]["id"] == asha["id"]
        assert notes["doctor"]["id"] == clinic.doctor["id"]
        assert notes["token"] == entry["token"]
        assert notes["visit_date"] == today().isoformat()
        # What the desk wrote down is where the complaint starts.
        assert notes["chief_complaint"] == "Cough for a week"
        assert notes["can_edit"] is True
        assert notes["can_add_addendum"] is False
        assert notes["appointment"] is None
        # The queue knows the notes are open, so it can offer them again.
        lane = lane_of(await the_queue(client), clinic.doctor)
        assert lane["now_seeing"]["consultation_id"] == notes["id"]

    async def test_asking_again_hands_back_the_same_notes(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        first = await opened(client, entry["id"])

        again = await open_notes(client, entry["id"])

        assert again.status_code == 200
        assert again.json()["data"]["id"] == first["id"]

    async def test_two_tabs_opening_at_once_share_one_set_of_notes(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)

        answers = await asyncio.gather(*(open_notes(client, entry["id"]) for _ in range(4)))

        assert sorted(answer.status_code for answer in answers) == [200, 200, 200, 201]
        assert len({answer.json()["data"]["id"] for answer in answers}) == 1

    async def test_a_booked_patient_carries_their_appointment_along(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        clinic = await a_clinic(client, outbox)
        made = await booked_today(session, client, await register(client), clinic.doctor)
        entry = await checked_in(client, made)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)

        notes = await opened(client, entry["id"])

        assert notes["appointment"]["id"] == made
        assert notes["appointment"]["status"] == "in_consultation"

    async def test_only_once_the_patient_is_in_the_room(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        waiting = await walked_in(client, await someone(client, "Asha"), clinic.doctor)
        called = await walked_in(client, await someone(client, "Bina"), clinic.doctor)
        await stepped(client, called["id"], "call")
        gone = await walked_in(client, await someone(client, "Chitra"), clinic.doctor)
        await stepped(client, gone["id"], "no-show")
        await become(client, clinic.doctor_email)

        for entry, words in (
            (waiting, "still waiting"),
            (called, "not come in yet"),
            (gone, "marked as gone"),
        ):
            refused = refusal(await open_notes(client, entry["id"]))
            assert refused["status"] == 409
            assert refused["code"] == "CONSULT_NOT_IN_ROOM"
            assert words in refused["message"]

    async def test_notes_can_still_be_written_after_the_patient_has_gone(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await stepped(client, entry["id"], "complete")
        await become(client, clinic.doctor_email)

        response = await open_notes(client, entry["id"])

        assert response.status_code == 201, response.text

    async def test_nobody_but_the_doctor_in_the_room_opens_them(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        receptionist = await invite_and_accept(client, role="receptionist", outbox=outbox)
        colleague_email, colleague = await linked_doctor(client, outbox, first_name="Vikram")
        entry = await in_the_room(client, await register(client), clinic.doctor)

        # The admin reads notes but is not a clinician, so does not write them.
        assert (await open_notes(client, entry["id"])).status_code == 403
        await become(client, receptionist)
        assert (await open_notes(client, entry["id"])).status_code == 403
        # Another doctor's patient is outside their line altogether.
        await become(client, colleague_email)
        assert (await open_notes(client, entry["id"])).status_code == 404
        assert colleague["id"] != clinic.doctor["id"]

    async def test_a_doctor_with_no_profile_is_told_why(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        unlinked = await invite_and_accept(client, role="doctor", outbox=outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, unlinked)

        refused = refusal(await open_notes(client, entry["id"]))

        assert refused["status"] == 403
        assert "not linked to a doctor profile" in refused["message"]

    async def test_unknown_and_malformed_places(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        await become(client, clinic.doctor_email)

        missing = refusal(await open_notes(client, "0192f0a1-0000-7000-8000-000000000000"))
        assert missing["status"] == 404
        assert refusal(await open_notes(client, "not-an-id"))["status"] == 422
        assert (await client.post(f"{API}/consultations", json={})).status_code == 422


class TestWriting:
    async def test_each_save_changes_only_what_was_sent(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor, reason="Fever")
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        notes = await saved(client, notes, history="Three days, worse at night.")
        assert notes["version"] == 2
        assert notes["chief_complaint"] == "Fever"
        assert notes["history"] == "Three days, worse at night."

        notes = await saved(client, notes, examination="  Temp 38.4, chest clear.  ")
        assert notes["version"] == 3
        assert notes["examination"] == "Temp 38.4, chest clear."
        assert notes["history"] == "Three days, worse at night."

        # Emptying a section clears it rather than keeping blank text.
        notes = await saved(client, notes, chief_complaint="   ")
        assert notes["chief_complaint"] is None

    async def test_a_save_from_an_older_copy_is_refused(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        stale = await opened(client, entry["id"])
        await saved(client, stale, advice="Rest and fluids.")

        refused = refusal(await save(client, stale, advice="Something else"))

        assert refused["status"] == 409
        assert refused["code"] == "CONSULT_EDITED_ELSEWHERE"
        kept = (await read(client, stale["id"])).json()["data"]
        assert kept["advice"] == "Rest and fluids."
        assert kept["version"] == 2

    async def test_two_tabs_saving_at_once_do_not_overwrite_each_other(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        answers = await asyncio.gather(
            save(client, notes, advice="From the first tab"),
            save(client, notes, advice="From the second tab"),
        )

        assert sorted(answer.status_code for answer in answers) == [200, 409]
        winner = next(answer for answer in answers if answer.status_code == 200)
        kept = (await read(client, notes["id"])).json()["data"]
        assert kept["advice"] == winner.json()["data"]["advice"]
        assert kept["version"] == 2

    async def test_diagnoses_are_listed_with_one_main_one(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        # One written on its own is the main one without saying so.
        notes = await saved(client, notes, diagnoses=[{"label": "Viral fever"}])
        assert notes["diagnoses"] == [{"label": "Viral fever", "is_primary": True}]
        assert notes["primary_diagnosis"] == "Viral fever"

        notes = await saved(
            client,
            notes,
            diagnoses=[
                {"label": "Viral fever"},
                {"label": "Type 2 diabetes", "is_primary": True},
            ],
        )
        assert notes["diagnoses"] == [
            {"label": "Viral fever", "is_primary": False},
            {"label": "Type 2 diabetes", "is_primary": True},
        ]
        assert notes["primary_diagnosis"] == "Type 2 diabetes"
        assert notes["diagnosis_count"] == 2

        notes = await saved(client, notes, diagnoses=[])
        assert notes["diagnoses"] == []
        assert notes["primary_diagnosis"] is None

    async def test_diagnoses_that_do_not_make_sense_are_refused(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        twice = refusal(
            await save(client, notes, diagnoses=[{"label": "Asthma"}, {"label": "  asthma "}])
        )
        assert twice["status"] == 422
        assert twice["fields"] == {"diagnoses.1.label": "That diagnosis is already listed."}

        two_main = refusal(
            await save(
                client,
                notes,
                diagnoses=[
                    {"label": "Asthma", "is_primary": True},
                    {"label": "Rhinitis", "is_primary": True},
                ],
            )
        )
        assert two_main["fields"] == {"diagnoses": "Only one diagnosis can be the main one."}

        blank = refusal(await save(client, notes, diagnoses=[{"label": "   "}]))
        assert blank["status"] == 422
        too_long = refusal(await save(client, notes, diagnoses=[{"label": "x" * 201}]))
        assert too_long["status"] == 422
        too_many = refusal(
            await save(client, notes, diagnoses=[{"label": f"D{n}"} for n in range(21)])
        )
        assert too_many["status"] == 422

        # None of that reached the notes.
        kept = (await read(client, notes["id"])).json()["data"]
        assert kept["diagnoses"] == []
        assert kept["version"] == 1

    async def test_a_follow_up_is_a_day_after_the_visit_and_within_a_year(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        for day, words in (
            (today(), "Pick a day after the visit."),
            (today() - dt.timedelta(days=3), "Pick a day after the visit."),
            (today() + dt.timedelta(days=366), "Keep a follow-up within a year of the visit."),
        ):
            refused = refusal(await save(client, notes, follow_up_date=day.isoformat()))
            assert refused["fields"] == {"follow_up_date": words}

        in_a_week = today() + dt.timedelta(days=7)
        notes = await saved(client, notes, follow_up_date=in_a_week.isoformat())
        assert notes["follow_up_date"] == in_a_week.isoformat()
        notes = await saved(client, notes, follow_up_date=None)
        assert notes["follow_up_date"] is None

    async def test_limits_on_what_a_save_carries(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        assert (await save(client, notes, chief_complaint="x" * 501)).status_code == 422
        assert (await save(client, notes, history="x" * 10_001)).status_code == 422
        assert (await save(client, notes, status="completed")).status_code == 422
        assert (await save(client, notes, doctor_id=clinic.doctor["id"])).status_code == 422
        assert (await save(client, notes, version=0)).status_code == 422
        no_version = await client.patch(
            f"{API}/consultations/{notes['id']}", json={"advice": "x"}
        )
        assert no_version.status_code == 422
        # A long history within the limit is fine.
        assert (await save(client, notes, history="x" * 10_000)).status_code == 200


class TestFinishing:
    async def test_finishing_locks_the_notes_and_closes_the_visit(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        clinic = await a_clinic(client, outbox)
        made = await booked_today(session, client, await register(client), clinic.doctor)
        entry = await checked_in(client, made)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])
        notes = await saved(client, notes, diagnoses=[{"label": "Migraine"}])

        done = await finished(client, notes)

        assert done["status"] == "completed"
        assert done["completed_at"] is not None
        assert done["can_edit"] is False
        assert done["can_add_addendum"] is True
        # The patient is finished in the queue and on the book as well.
        lane = lane_of(await the_queue(client), clinic.doctor)
        assert lane["now_seeing"] is None
        assert lane["done"][0]["id"] == entry["id"]
        assert lane["done"][0]["status"] == "completed"
        await become(client, clinic.admin)
        booked = await appointment(client, made)
        assert booked["status"] == "completed"
        # And the appointment points at what was written.
        assert booked["consultation_id"] == notes["id"]

    async def test_finishing_frees_the_room_for_the_next_patient(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        first = await in_the_room(client, await someone(client, "Asha"), clinic.doctor)
        second = await walked_in(client, await someone(client, "Bina"), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, first["id"])
        notes = await saved(client, notes, advice="Review in a week.")

        assert (await step(client, second["id"], "start")).status_code == 409
        await finished(client, notes)
        assert (await step(client, second["id"], "start")).status_code == 200

    async def test_notes_with_nothing_in_them_are_not_finished(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        refused = refusal(await finish(client, notes))

        assert refused["status"] == 422
        assert refused["fields"] == {
            "notes": "Write the complaint or a diagnosis before finishing."
        }
        assert (await read(client, notes["id"])).json()["data"]["status"] == "draft"
        # The patient is still in the room.
        lane = lane_of(await the_queue(client), clinic.doctor)
        assert lane["now_seeing"]["id"] == entry["id"]

    async def test_finishing_from_an_older_copy_is_refused(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor, reason="Rash")
        await become(client, clinic.doctor_email)
        stale = await opened(client, entry["id"])
        await saved(client, stale, advice="Calamine twice a day.")

        refused = refusal(await finish(client, stale))

        assert refused["code"] == "CONSULT_EDITED_ELSEWHERE"
        assert (await read(client, stale["id"])).json()["data"]["status"] == "draft"

    async def test_finished_notes_cannot_be_changed_or_finished_again(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor, reason="Rash")
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])
        done = await finished(client, notes)

        again = refusal(await finish(client, done))
        assert again["status"] == 409
        assert again["code"] == "CONSULT_ALREADY_COMPLETED"
        edit = refusal(await save(client, done, advice="Changed my mind"))
        assert edit["code"] == "CONSULT_ALREADY_COMPLETED"
        assert (await read(client, notes["id"])).json()["data"]["advice"] is None

    async def test_a_double_clicked_finish_goes_through_once(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor, reason="Rash")
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        answers = await asyncio.gather(finish(client, notes), finish(client, notes))

        assert sorted(answer.status_code for answer in answers) == [200, 409]

    async def test_the_queue_can_be_finished_first_and_the_notes_later(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor, reason="Rash")
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])
        await stepped(client, entry["id"], "complete")

        # Still a draft, and still on the doctor's list of notes to finish.
        drafts = await listing(client, status="draft")
        assert [item["id"] for item in drafts["items"]] == [notes["id"]]

        done = await finished(client, notes)
        assert done["status"] == "completed"
        assert (await listing(client, status="draft"))["total"] == 0


class TestAddenda:
    async def test_finished_notes_are_added_to_not_rewritten(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor, reason="Rash")
        await become(client, clinic.doctor_email)
        notes = await finished(client, await opened(client, entry["id"]))

        first = await add_addendum(client, notes, "Culture came back negative.")
        assert first.status_code == 201, first.text
        second = await add_addendum(client, notes, "  Phoned the patient with the result.  ")
        assert second.status_code == 201, second.text

        found = second.json()["data"]
        assert [added["body"] for added in found["addenda"]] == [
            "Culture came back negative.",
            "Phoned the patient with the result.",
        ]
        assert all(added["written_by"] for added in found["addenda"])
        assert found["addendum_count"] == 2
        # The notes themselves have not moved.
        assert found["chief_complaint"] == "Rash"
        assert found["status"] == "completed"

    async def test_a_draft_is_changed_directly_rather_than_added_to(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        refused = refusal(await add_addendum(client, notes, "Too early"))

        assert refused["status"] == 409
        assert refused["code"] == "CONSULT_STILL_DRAFT"

    async def test_an_addendum_needs_something_in_it(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor, reason="Rash")
        await become(client, clinic.doctor_email)
        notes = await finished(client, await opened(client, entry["id"]))

        assert (await add_addendum(client, notes, "   ")).status_code == 422
        assert (await add_addendum(client, notes, "x" * 5001)).status_code == 422
        assert (await read(client, notes["id"])).json()["data"]["addenda"] == []


class TestWhoSeesWhat:
    async def test_a_doctor_reads_their_own_notes_and_not_a_colleagues(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        colleague_email, colleague = await linked_doctor(client, outbox, first_name="Vikram")
        asha = await someone(client, "Asha")
        mine = await in_the_room(client, asha, clinic.doctor, reason="Cough")
        theirs = await in_the_room(client, await someone(client, "Bina"), colleague)

        await become(client, colleague_email)
        their_notes = await opened(client, theirs["id"])
        await become(client, clinic.doctor_email)
        my_notes = await opened(client, mine["id"])

        # Their own list, whichever doctor they ask about.
        own = await listing(client, doctor_id=colleague["id"])
        assert [item["id"] for item in own["items"]] == [my_notes["id"]]

        refused = refusal(await read(client, their_notes["id"]))
        assert refused["status"] == 403
        assert refused["code"] == "CONSULT_NOT_OWNER"
        for attempt in (
            await save(client, their_notes, advice="Not mine to write"),
            await finish(client, their_notes),
            await add_addendum(client, their_notes, "Not mine either"),
        ):
            assert refusal(attempt)["code"] == "CONSULT_NOT_OWNER"

    async def test_the_clinic_admin_reads_every_doctors_notes_but_writes_none(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        colleague_email, colleague = await linked_doctor(client, outbox, first_name="Vikram")
        mine = await in_the_room(client, await someone(client, "Asha"), clinic.doctor)
        theirs = await in_the_room(client, await someone(client, "Bina"), colleague)
        await become(client, clinic.doctor_email)
        mine_notes = await saved(client, await opened(client, mine["id"]), advice="Rest")
        await become(client, colleague_email)
        await opened(client, theirs["id"])

        await become(client, clinic.admin)
        everyone = await listing(client)
        assert everyone["total"] == 2
        just_one = await listing(client, doctor_id=clinic.doctor["id"])
        assert [item["id"] for item in just_one["items"]] == [mine_notes["id"]]

        found = (await read(client, mine_notes["id"])).json()["data"]
        assert found["advice"] == "Rest"
        assert found["can_edit"] is False
        assert (await save(client, found, advice="Admin edit")).status_code == 403
        assert (await finish(client, found)).status_code == 403

    async def test_the_desk_and_staff_cannot_read_notes(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        receptionist = await invite_and_accept(client, role="receptionist", outbox=outbox)
        staff = await invite_and_accept(client, role="staff", outbox=outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        for address in (receptionist, staff):
            await become(client, address)
            assert (await read(client, notes["id"])).status_code == 403
            assert (await client.get(f"{API}/consultations")).status_code == 403

    async def test_another_clinic_cannot_see_or_touch_them(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor, reason="Rash")
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        await client.post(f"{AUTH}/logout")
        other = await a_clinic(client, outbox)
        assert (await read(client, notes["id"])).status_code == 404
        assert (await listing(client))["total"] == 0
        await become(client, other.doctor_email)
        assert (await read(client, notes["id"])).status_code == 404
        assert (await save(client, notes, advice="x")).status_code == 404
        assert (await finish(client, notes)).status_code == 404
        assert (await add_addendum(client, notes, "x")).status_code == 404
        assert (await open_notes(client, entry["id"])).status_code == 404

    async def test_a_doctor_with_no_profile_sees_no_notes(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        unlinked = await invite_and_accept(client, role="doctor", outbox=outbox)
        entry = await in_the_room(client, await register(client), clinic.doctor)
        await become(client, clinic.doctor_email)
        notes = await opened(client, entry["id"])

        await become(client, unlinked)
        assert (await listing(client))["items"] == []
        assert (await read(client, notes["id"])).status_code == 404

    async def test_a_patients_visits_newest_first_and_paged(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        asha = await someone(client, "Asha")
        bina = await someone(client, "Bina")
        ids = []
        for patient in (asha, bina, asha):
            entry = await in_the_room(client, patient, clinic.doctor, reason="Review")
            await become(client, clinic.doctor_email)
            ids.append((await finished(client, await opened(client, entry["id"])))["id"])
            await become(client, clinic.admin)

        hers = await listing(client, patient_id=asha["id"])
        assert [item["id"] for item in hers["items"]] == [ids[2], ids[0]]
        assert hers["total"] == 2
        paged = await listing(client, limit=1, offset=1)
        assert paged["total"] == 3
        assert [item["id"] for item in paged["items"]] == [ids[1]]
        no_rows = await client.get(f"{API}/consultations", params={"limit": 0})
        assert no_rows.status_code == 422
        assert (
            await client.get(f"{API}/consultations", params={"status": "open"})
        ).status_code == 422
