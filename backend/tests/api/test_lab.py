"""Lab orders: asked for in the room, typed in by the desk when the report
comes back, and marked seen by the doctor who ordered them."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LabOrder
from tests.api.test_appointments import doctor_with_hours
from tests.api.test_clinic import AUTH, invite_and_accept, sign_in, sign_up
from tests.api.test_consultations import Clinic, a_clinic, become, finished, opened, saved
from tests.api.test_patients import register
from tests.api.test_queue import refusal, stepped, today, walked_in
from tests.conftest import Outbox

API = "/api/v1"
# Thousands per microlitre, as the list of tests writes it.
THOUSANDS = "×10³/µL"  # noqa: RUF001

ANAEMIC = [
    {"name": "Haemoglobin", "value": "10.4", "unit": "g/dL", "low": 12, "high": 15},
    {"name": "Total leucocyte count", "value": "12.6", "unit": THOUSANDS, "low": 4, "high": 11},
    {"name": "Platelet count", "value": "250", "unit": THOUSANDS, "low": 150, "high": 410},
]


async def in_the_room(
    client: AsyncClient, outbox: Outbox, **details: Any
) -> tuple[Clinic, dict[str, Any], dict[str, Any]]:
    """A clinic, a patient in with its doctor, and the doctor signed in with
    the notes open."""
    clinic = await a_clinic(client, outbox)
    patient = await register(client, **details)
    entry = await walked_in(client, patient, clinic.doctor)
    await stepped(client, entry["id"], "start")
    await become(client, clinic.doctor_email)
    return clinic, patient, await opened(client, entry["id"])


async def seen_again(
    client: AsyncClient, clinic: Clinic, patient: dict[str, Any]
) -> dict[str, Any]:
    """The same patient back in the room for another visit, with the doctor
    signed in on the new notes."""
    await become(client, clinic.admin)
    entry = await walked_in(client, patient, clinic.doctor)
    await stepped(client, entry["id"], "start")
    await become(client, clinic.doctor_email)
    return await opened(client, entry["id"])


async def order(client: AsyncClient, notes: dict[str, Any], **body: Any) -> Response:
    return await client.post(f"{API}/lab-orders", json={"consultation_id": notes["id"], **body})


async def ordered(client: AsyncClient, notes: dict[str, Any], **body: Any) -> dict[str, Any]:
    response = await order(client, notes, **body)
    assert response.status_code == 201, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def report(client: AsyncClient, order_id: str, **body: Any) -> Response:
    payload = {"reported_on": today().isoformat(), **body}
    return await client.put(f"{API}/lab-orders/{order_id}/result", json=payload)


async def reported(client: AsyncClient, order_id: str, **body: Any) -> dict[str, Any]:
    response = await report(client, order_id, **body)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def one(client: AsyncClient, order_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/lab-orders/{order_id}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def listing(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/lab-orders", params=params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


async def review(client: AsyncClient, order_id: str) -> Response:
    return await client.post(f"{API}/lab-orders/{order_id}/review")


async def cancel(
    client: AsyncClient, order_id: str, reason: str = "Had it done elsewhere"
) -> Response:
    return await client.post(f"{API}/lab-orders/{order_id}/cancel", json={"reason": reason})


def by_name(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {value["name"]: value for value in found["values"]}


class TestOrdering:
    async def test_a_listed_test_carries_its_preparation(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient, notes = await in_the_room(client, outbox)

        found = await ordered(client, notes, test_code="lipid")

        assert found["order_number"] == "LAB-000001"
        assert found["test_name"] == "Lipid profile"
        assert found["category"] == "chemistry"
        assert found["status"] == "ordered"
        assert found["urgent"] is False
        assert found["instructions"].startswith("Nothing to eat for 10 to 12 hours")
        assert found["patient"]["id"] == patient["id"]
        assert found["doctor"]["id"] == clinic.doctor["id"]
        assert found["consultation_id"] == notes["id"]
        assert found["visit_open"] is True
        assert found["ordered_by"]
        assert found["values"] == []
        assert (found["can_remove"], found["can_cancel"]) == (True, False)
        # Ordering is not the same as typing results in.
        assert (found["can_enter"], found["can_review"]) == (True, False)

        again = await ordered(client, notes, test_code="tsh", urgent=True)
        assert again["order_number"] == "LAB-000002"
        assert again["urgent"] is True
        assert again["instructions"] is None

    async def test_the_lines_to_fill_in_fit_the_patient(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)

        found = await ordered(client, notes, test_code="cbc")

        # An adult woman, so her own ranges where they differ from a man's.
        lines = {line["name"]: line for line in found["template"]}
        assert (lines["Haemoglobin"]["low"], lines["Haemoglobin"]["high"]) == (12, 15)
        assert lines["Haemoglobin"]["unit"] == "g/dL"
        assert (lines["Platelet count"]["low"], lines["Platelet count"]["high"]) == (150, 410)
        assert found["ranges_left_out"] is False
        assert len(found["template"]) == 14

    async def test_a_child_gets_no_ranges_to_copy(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        born = dt.date(today().year - 6, 1, 1).isoformat()
        _, _, notes = await in_the_room(client, outbox, date_of_birth=born, gender="male")

        found = await ordered(client, notes, test_code="urine_routine")

        lines = {line["name"]: line for line in found["template"]}
        assert (lines["Pus cells"]["low"], lines["Pus cells"]["high"]) == (None, None)
        # A word that should come back is the same at any age.
        assert lines["Protein"]["expected"] == "Nil"
        assert found["ranges_left_out"] is True

    async def test_without_a_sex_only_the_ranges_that_depend_on_it_are_left(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox, gender="other")

        found = await ordered(client, notes, test_code="cbc")

        lines = {line["name"]: line for line in found["template"]}
        assert lines["Haemoglobin"]["low"] is None
        assert lines["MCV"]["low"] == 83
        assert found["ranges_left_out"] is True

    async def test_a_name_the_list_knows_is_the_listed_test(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_name="  hemogram ")
        assert (found["test_code"], found["test_name"]) == ("cbc", "Complete blood count")

    async def test_a_test_the_list_does_not_carry(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)

        found = await ordered(
            client, notes, test_name="X-ray  left knee AP and lateral", instructions="Standing"
        )

        assert found["test_code"] is None
        assert found["test_name"] == "X-ray left knee AP and lateral"
        assert found["category"] is None
        assert found["instructions"] == "Standing"
        assert found["template"] == []

        # The clinic's own tests are offered back the next time.
        listed = (await client.get(f"{API}/lab-tests")).json()["data"]
        own = [test for test in listed["tests"] if test["code"] is None]
        assert own == [
            {
                "code": None,
                "name": "X-ray left knee AP and lateral",
                "also": [],
                "category": None,
                "prepare": None,
                "parts": 0,
                "times_ordered": 1,
            }
        ]

    async def test_preparation_can_be_changed_or_left_off(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)
        changed = await ordered(client, notes, test_code="fbs", instructions="From 9 pm")
        assert changed["instructions"] == "From 9 pm"
        left_off = await ordered(client, notes, test_code="lipid", instructions="  ")
        assert left_off["instructions"] is None

    async def test_the_same_test_twice_on_one_visit(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)
        await ordered(client, notes, test_code="cbc")

        for body in ({"test_code": "cbc"}, {"test_name": "CBC"}):
            refused = refusal(await order(client, notes, **body))
            assert (refused["status"], refused["code"]) == (409, "LAB_ALREADY_ORDERED")
            assert refused["message"] == (
                "Complete blood count is already ordered on this visit."
            )

        typed = await ordered(client, notes, test_name="Serum amylase")
        refused = refusal(await order(client, notes, test_name="serum AMYLASE"))
        assert refused["code"] == "LAB_ALREADY_ORDERED"

        # Taken back, it can be asked for again.
        await client.delete(f"{API}/lab-orders/{typed['id']}")
        await ordered(client, notes, test_name="Serum amylase")

    async def test_two_tabs_ordering_the_same_test_at_once(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)

        answers = await asyncio.gather(
            order(client, notes, test_code="hba1c"), order(client, notes, test_code="hba1c")
        )

        assert sorted(answer.status_code for answer in answers) == [201, 409]
        assert (await listing(client, consultation_id=notes["id"]))["total"] == 1

    async def test_what_cannot_be_ordered(self, client: AsyncClient, outbox: Outbox) -> None:
        _, _, notes = await in_the_room(client, outbox)

        refused = refusal(await order(client, notes, test_code="not-a-test"))
        assert refused["fields"] == {"test_code": "That test is not on the list."}
        for body in ({}, {"test_name": "   "}):
            refused = refusal(await order(client, notes, **body))
            assert refused["fields"] == {"test_name": "Say which test."}
        refused = refusal(await order(client, notes, test_name="x" * 121))
        assert refused["status"] == 422
        refused = refusal(
            await client.post(
                f"{API}/lab-orders",
                json={"consultation_id": str(uuid.uuid4()), "test_code": "cbc"},
            )
        )
        assert refused["fields"] == {"consultation_id": "Those notes could not be found."}

    async def test_thirty_is_as_many_as_one_visit_takes(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)
        for n in range(30):
            await ordered(client, notes, test_name=f"Test number {n}")
        refused = refusal(await order(client, notes, test_name="One more"))
        assert refused["status"] == 422
        assert "30 tests" in refused["message"]

    async def test_not_once_the_visit_is_finished(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)
        await finished(client, await saved(client, notes, chief_complaint="Tired"))

        refused = refusal(await order(client, notes, test_code="cbc"))
        assert (refused["status"], refused["code"]) == (409, "LAB_VISIT_CLOSED")

    async def test_only_the_doctor_seeing_the_patient_orders(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)

        # A colleague, linked to their own profile.
        await become(client, clinic.admin)
        colleague = await invite_and_accept(client, role="doctor", outbox=outbox)
        staff_id = next(
            member["id"]
            for member in (await client.get(f"{API}/staff")).json()["data"]
            if member["email"] == colleague
        )
        await doctor_with_hours(client, first_name="Farhan", user_id=staff_id)
        await become(client, colleague)
        refused = refusal(await order(client, notes, test_code="cbc"))
        assert (refused["status"], refused["code"]) == (403, "LAB_NOT_ORDERER")

        # The admin and the desk do not order tests at all.
        await become(client, clinic.admin)
        assert refusal(await order(client, notes, test_code="cbc"))["status"] == 403
        desk = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, desk)
        assert refusal(await order(client, notes, test_code="cbc"))["status"] == 403

    async def test_a_doctor_account_with_no_profile(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)
        await client.post(f"{AUTH}/logout")
        await sign_up(client)
        loose = await invite_and_accept(client, role="doctor", outbox=outbox)
        await become(client, loose)

        refused = refusal(await order(client, notes, test_code="cbc"))
        assert refused["status"] == 403
        assert "not linked to a doctor profile" in refused["message"]


class TestTakingBack:
    async def test_removed_while_the_patient_is_still_in(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="esr")

        removed = await client.delete(f"{API}/lab-orders/{found['id']}")

        assert removed.status_code == 200, removed.text
        missing = refusal(await client.get(f"{API}/lab-orders/{found['id']}"))
        assert (missing["status"], missing["code"]) == (404, "LAB_NOT_FOUND")
        assert (await listing(client, consultation_id=notes["id"]))["total"] == 0

    async def test_once_the_visit_is_finished_it_is_cancelled_instead(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="esr")
        await finished(client, await saved(client, notes, chief_complaint="Joint pain"))

        refused = refusal(await client.delete(f"{API}/lab-orders/{found['id']}"))
        assert (refused["status"], refused["code"]) == (409, "LAB_LOCKED")
        assert refused["message"].endswith("Cancel it instead.")

        now = await one(client, found["id"])
        assert (now["visit_open"], now["can_remove"], now["can_cancel"]) == (False, False, True)
        response = await cancel(client, found["id"], "Patient could not afford it")
        assert response.status_code == 200, response.text
        done = response.json()["data"]
        assert done["status"] == "cancelled"
        assert done["cancel_reason"] == "Patient could not afford it"
        assert done["cancelled_by"]
        assert done["cancelled_at"]
        assert not any((done["can_cancel"], done["can_enter"], done["can_remove"]))

        refused = refusal(await cancel(client, found["id"]))
        assert refused["message"] == "It has already been cancelled."
        refused = refusal(await report(client, found["id"], findings="Normal"))
        assert (refused["status"], refused["code"]) == (409, "LAB_LOCKED")

    async def test_the_desk_cancels_with_a_reason(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="usg_abdomen")
        await become(client, clinic.admin)
        desk = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, desk)

        assert (await one(client, found["id"]))["can_cancel"] is True
        for blank in ("", "   "):
            assert refusal(await cancel(client, found["id"], blank))["status"] == 422
        response = await cancel(client, found["id"], "Done at the hospital last week")
        assert response.status_code == 200, response.text

    async def test_nothing_with_a_result_is_taken_back(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="xray_chest")
        await become(client, clinic.admin)
        await reported(client, found["id"], findings="No active lung lesion.")
        await become(client, clinic.doctor_email)

        refused = refusal(await client.delete(f"{API}/lab-orders/{found['id']}"))
        assert refused["message"] == "It has a result now, so it stays on the record."
        refused = refusal(await cancel(client, found["id"]))
        assert refused["message"] == "It has a result now, so it cannot be cancelled."

    async def test_only_the_doctor_who_ordered_it_removes_it(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="esr")
        await become(client, clinic.admin)
        # The admin records results but does not order, so has no way to remove.
        assert refusal(await client.delete(f"{API}/lab-orders/{found['id']}"))["status"] == 403


class TestResults:
    async def test_the_desk_types_the_report_in(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="cbc")
        await become(client, clinic.admin)
        desk = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, desk)

        done = await reported(
            client,
            found["id"],
            lab_name="  City Diagnostics ",
            findings="Microcytic picture.",
            values=ANAEMIC,
        )

        assert done["status"] == "resulted"
        assert done["reported_on"] == today().isoformat()
        assert done["lab_name"] == "City Diagnostics"
        assert done["findings"] == "Microcytic picture."
        assert done["resulted_by"] == "Joiner Person"
        assert done["resulted_at"]
        assert done["changed_by"] is None
        values = by_name(done)
        assert values["Haemoglobin"]["flag"] == "low"
        assert values["Total leucocyte count"]["flag"] == "high"
        assert values["Platelet count"]["flag"] is None
        assert [value["name"] for value in done["values"]] == [line["name"] for line in ANAEMIC]
        assert values["Haemoglobin"]["earlier"] is None
        assert done["flagged"] == 2
        # Marking it seen is the doctor's.
        assert (done["can_enter"], done["can_review"]) == (True, False)

    async def test_words_are_judged_against_the_word_they_should_be(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="urine_routine")
        await become(client, clinic.admin)

        done = await reported(
            client,
            found["id"],
            values=[
                {"name": "Protein", "value": "Trace", "expected": "Nil"},
                {"name": "Sugar", "value": "Negative", "expected": "Nil"},
                {"name": "Ketones", "value": "absent", "expected": "Nil"},
                {"name": "Colour", "value": "Pale yellow"},
                {"name": "Pus cells", "value": "8-10", "unit": "/hpf", "low": 0, "high": 5},
                {"name": "pH", "value": "6.0", "low": 5, "high": 8},
            ],
        )

        values = by_name(done)
        assert values["Protein"]["flag"] == "abnormal"
        assert values["Sugar"]["flag"] is None
        assert values["Ketones"]["flag"] is None
        assert values["Colour"]["flag"] is None
        # A range typed as a range is not a number, so it is left to the eye.
        assert values["Pus cells"]["flag"] is None
        assert values["pH"]["flag"] is None
        assert done["flagged"] == 1

    async def test_a_scan_is_only_words(self, client: AsyncClient, outbox: Outbox) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="ecg")
        assert found["template"] == []
        await become(client, clinic.admin)

        words = "Sinus rhythm, rate 78. Normal axis."
        done = await reported(client, found["id"], findings=words)

        assert done["values"] == []
        assert done["findings"] == words
        assert done["flagged"] == 0

    async def test_a_correction_replaces_the_whole_report(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="cbc")
        await become(client, clinic.admin)
        first = await reported(client, found["id"], values=ANAEMIC, lab_name="City")

        second = await reported(client, found["id"], values=ANAEMIC[:1])

        assert second["status"] == "resulted"
        assert [value["name"] for value in second["values"]] == ["Haemoglobin"]
        assert second["lab_name"] is None
        assert second["resulted_at"] == first["resulted_at"]
        assert second["resulted_by"] == first["resulted_by"]
        assert second["changed_by"]

    async def test_a_report_typed_against_the_wrong_order_comes_off(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="cbc")
        await become(client, clinic.admin)
        await reported(client, found["id"], values=ANAEMIC, lab_name="City")

        response = await client.delete(f"{API}/lab-orders/{found['id']}/result")

        assert response.status_code == 200, response.text
        cleared = response.json()["data"]
        assert cleared["status"] == "ordered"
        assert cleared["values"] == []
        assert (cleared["reported_on"], cleared["lab_name"], cleared["resulted_by"]) == (
            None,
            None,
            None,
        )
        refused = refusal(await client.delete(f"{API}/lab-orders/{found['id']}/result"))
        assert refused["message"] == "There is no result on this order to take off."

    async def test_what_a_report_cannot_say(self, client: AsyncClient, outbox: Outbox) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="cbc")
        await become(client, clinic.admin)
        tomorrow = (today() + dt.timedelta(days=1)).isoformat()
        yesterday = (today() - dt.timedelta(days=1)).isoformat()

        refused = refusal(await report(client, found["id"], reported_on=tomorrow, findings="."))
        assert refused["fields"] == {"reported_on": "The report cannot be dated after today."}
        refused = refusal(
            await report(client, found["id"], reported_on=yesterday, findings=".")
        )
        assert list(refused["fields"]) == ["reported_on"]
        assert "cannot be dated before that" in refused["fields"]["reported_on"]

        refused = refusal(await report(client, found["id"]))
        assert refused["fields"] == {
            "values": "Type in at least one value, or what the report says."
        }
        refused = refusal(await report(client, found["id"], findings="   ", values=[]))
        assert "values" in refused["fields"]

        refused = refusal(
            await report(
                client,
                found["id"],
                values=[
                    {"name": "Haemoglobin", "value": "11"},
                    {"name": " haemoglobin ", "value": "12"},
                    {"name": "MCV", "value": "  "},
                    {"name": "MCH", "value": "29", "low": 32, "high": 27},
                ],
            )
        )
        assert refused["fields"] == {
            "values.1.name": "haemoglobin is already on the report.",
            "values.2.value": "Type the value, or take the line out.",
            "values.3.high": "The top of the range is below the bottom.",
        }
        assert (await one(client, found["id"]))["status"] == "ordered"

        for bad in (
            {"values": [{"name": "", "value": "1"}]},
            {"values": [{"name": "Hb", "value": "1" * 61}]},
            {"values": [{"name": "Hb", "value": "1", "low": "abc"}]},
            {"values": [{"name": f"V{n}", "value": "1"} for n in range(41)]},
            {"findings": "x" * 5001},
            {"reported_on": "not a date", "findings": "x"},
        ):
            assert refusal(await report(client, found["id"], **bad))["status"] == 422

    async def test_the_doctor_marks_it_seen_and_then_it_stays(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="cbc")
        refused = refusal(await review(client, found["id"]))
        assert refused["message"] == "There is no result to look at yet."

        await become(client, clinic.admin)
        await reported(client, found["id"], values=ANAEMIC)
        # The admin can type it in but not mark it seen.
        assert refusal(await review(client, found["id"]))["status"] == 403
        await become(client, clinic.doctor_email)
        assert (await one(client, found["id"]))["can_review"] is True

        response = await review(client, found["id"])

        assert response.status_code == 200, response.text
        seen = response.json()["data"]
        assert seen["status"] == "reviewed"
        assert seen["reviewed_by"]
        assert seen["reviewed_at"]
        assert not any((seen["can_review"], seen["can_enter"], seen["can_cancel"]))
        refused = refusal(await review(client, found["id"]))
        assert refused["message"] == "You have already marked this result as seen."

        await become(client, clinic.admin)
        refused = refusal(await report(client, found["id"], values=ANAEMIC[:1]))
        assert refused["message"] == (
            "The doctor has already seen this result, so it stays as it was."
        )
        refused = refusal(await client.delete(f"{API}/lab-orders/{found['id']}/result"))
        assert refused["code"] == "LAB_LOCKED"

    async def test_only_the_doctor_who_ordered_it_marks_it_seen(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="tsh")
        await become(client, clinic.admin)
        await reported(client, found["id"], values=[{"name": "TSH", "value": "6.1"}])
        colleague = await invite_and_accept(client, role="doctor", outbox=outbox)
        staff_id = next(
            member["id"]
            for member in (await client.get(f"{API}/staff")).json()["data"]
            if member["email"] == colleague
        )
        await doctor_with_hours(client, first_name="Farhan", user_id=staff_id)
        await become(client, colleague)

        # The record is open to every doctor, the actions on it are not.
        theirs = await one(client, found["id"])
        assert theirs["values"][0]["value"] == "6.1"
        assert (theirs["can_review"], theirs["can_enter"]) == (False, False)
        refused = refusal(await review(client, found["id"]))
        assert (refused["status"], refused["code"]) == (403, "LAB_NOT_ORDERER")
        refused = refusal(await report(client, found["id"], findings="Fine"))
        assert (refused["status"], refused["code"]) == (404, "LAB_NOT_FOUND")

    async def test_the_last_report_of_the_same_test_is_set_beside(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        clinic, patient, notes = await in_the_room(client, outbox)
        first = await ordered(client, notes, test_code="cbc")
        await finished(client, await saved(client, notes, chief_complaint="Tired"))
        await become(client, clinic.admin)
        await reported(
            client,
            first["id"],
            values=[
                {"name": "Haemoglobin", "value": "9.1", "unit": "g/dL", "low": 12, "high": 15},
                {"name": "Platelet count", "value": "2.5", "unit": "lakh/µL"},
            ],
        )
        # A month ago, as far as the order is concerned.
        await session.execute(
            update(LabOrder)
            .where(LabOrder.id == uuid.UUID(first["id"]))
            .values(ordered_at=LabOrder.ordered_at - dt.timedelta(days=30))
        )
        await session.commit()

        later_notes = await seen_again(client, clinic, patient)
        second = await ordered(client, later_notes, test_code="cbc")
        await become(client, clinic.admin)
        done = await reported(
            client,
            second["id"],
            values=[
                {"name": "Haemoglobin", "value": "11.8", "unit": "g/dL", "low": 12, "high": 15},
                {"name": "Platelet count", "value": "260", "unit": THOUSANDS},
            ],
        )

        values = by_name(done)
        assert values["Haemoglobin"]["earlier"] == {
            "value": "9.1",
            "flag": "low",
            "reported_on": today().isoformat(),
        }
        # Counted differently last time, so the two numbers are not set side by side.
        assert values["Platelet count"]["earlier"] is None
        # And the older report is not compared with the newer one.
        assert by_name(await one(client, first["id"]))["Haemoglobin"]["earlier"] is None


class TestReading:
    async def test_the_work_list(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        clinic, patient, notes = await in_the_room(client, outbox)
        oldest = await ordered(client, notes, test_code="lipid")
        middle = await ordered(client, notes, test_code="fbs")
        urgent = await ordered(client, notes, test_code="dengue_ns1", urgent=True)
        typed_in = await ordered(client, notes, test_code="tsh")
        gone = await ordered(client, notes, test_code="esr")
        for n, found in enumerate((oldest, middle, urgent, typed_in, gone)):
            await session.execute(
                update(LabOrder)
                .where(LabOrder.id == uuid.UUID(found["id"]))
                .values(ordered_at=LabOrder.ordered_at - dt.timedelta(minutes=50 - n))
            )
        await session.commit()
        await finished(client, await saved(client, notes, chief_complaint="Fever"))
        await cancel(client, gone["id"])
        await become(client, clinic.admin)
        await reported(client, typed_in["id"], values=[{"name": "TSH", "value": "2"}])

        waiting = await listing(client, show="waiting")
        assert [item["id"] for item in waiting["items"]] == [
            urgent["id"],
            oldest["id"],
            middle["id"],
        ]
        assert waiting["total"] == 3
        assert waiting["counts"] == {"ordered": 3, "resulted": 1, "reviewed": 0, "cancelled": 1}
        assert [i["id"] for i in (await listing(client, show="to_review"))["items"]] == [
            typed_in["id"]
        ]
        assert [i["id"] for i in (await listing(client, show="cancelled"))["items"]] == [
            gone["id"]
        ]
        assert (await listing(client, show="open"))["total"] == 4
        everything = await listing(client)
        assert everything["total"] == 5
        # Newest first once it is not a list of what is waiting.
        assert everything["items"][0]["id"] == gone["id"]

        first_page = await listing(client, show="waiting", limit=2)
        assert [i["id"] for i in first_page["items"]] == [urgent["id"], oldest["id"]]
        assert first_page["total"] == 3
        rest = await listing(client, show="waiting", limit=2, offset=2)
        assert [i["id"] for i in rest["items"]] == [middle["id"]]

        by_patient = await listing(client, patient_id=patient["id"])
        assert by_patient["total"] == 5
        assert (await listing(client, doctor_id=clinic.doctor["id"]))["total"] == 5
        assert (await listing(client, doctor_id=str(uuid.uuid4())))["total"] == 0

    async def test_a_visits_tests_in_the_order_they_were_asked_for(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await in_the_room(client, outbox)
        first = await ordered(client, notes, test_code="lipid")
        second = await ordered(client, notes, test_code="tsh", urgent=True)
        third = await ordered(client, notes, test_code="cbc")

        found = await listing(client, consultation_id=notes["id"])

        assert [item["id"] for item in found["items"]] == [
            first["id"],
            second["id"],
            third["id"],
        ]

    async def test_a_doctors_own_orders(self, client: AsyncClient, outbox: Outbox) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        await ordered(client, notes, test_code="cbc")

        assert (await listing(client, mine="true"))["total"] == 1
        # Anyone who is not a doctor has no list of their own, so sees the clinic's.
        await become(client, clinic.admin)
        assert (await listing(client, mine="true"))["total"] == 1
        colleague = await invite_and_accept(client, role="doctor", outbox=outbox)
        await become(client, colleague)
        mine = await listing(client, mine="true")
        assert (mine["items"], mine["total"]) == ([], 0)
        assert set(mine["counts"].values()) == {0}
        assert (await listing(client))["total"] == 1

    async def test_searching_the_list(self, client: AsyncClient, outbox: Outbox) -> None:
        clinic, patient, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="lipid")
        await become(client, clinic.admin)

        for typed in (
            "aarti",
            "AARTI DESH",
            patient["patient_number"].lower(),
            "98200112",
            found["order_number"],
            "lipid",
        ):
            assert (await listing(client, q=typed))["total"] == 1, typed
        for typed in ("rohan", "%", "_", "cbc"):
            assert (await listing(client, q=typed))["total"] == 0, typed
        assert (await listing(client, q="   "))["total"] == 1

    async def test_the_list_of_tests(self, client: AsyncClient, outbox: Outbox) -> None:
        _, _, notes = await in_the_room(client, outbox)
        await ordered(client, notes, test_code="cbc")

        listed = (await client.get(f"{API}/lab-tests")).json()["data"]

        assert listed["categories"]["blood"] == "Blood counts"
        tests = {test["code"]: test for test in listed["tests"]}
        assert tests["cbc"]["times_ordered"] == 1
        assert tests["cbc"]["parts"] == 14
        assert "Hemogram" in tests["cbc"]["also"]
        assert tests["lipid"]["times_ordered"] == 0
        assert tests["ecg"]["parts"] == 0
        assert all(test["category"] in listed["categories"] for test in listed["tests"])

    async def test_the_doctors_first_page_shows_what_came_back(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="cbc", urgent=True)
        await ordered(client, notes, test_code="esr")
        day = (await client.get(f"{API}/dashboard/summary")).json()["data"]
        assert (day["results"], day["results_total"]) == ([], 0)

        await become(client, clinic.admin)
        await reported(client, found["id"], values=ANAEMIC)
        # The desk's page is the clinic's day, which has no list of results.
        desk_day = (await client.get(f"{API}/dashboard/summary")).json()["data"]
        assert desk_day["results"] == []
        await become(client, clinic.doctor_email)

        day = (await client.get(f"{API}/dashboard/summary")).json()["data"]
        assert day["results_total"] == 1
        assert day["results"] == [
            {
                "order_id": found["id"],
                "patient": day["results"][0]["patient"],
                "test_name": "Complete blood count",
                "reported_on": today().isoformat(),
                "urgent": True,
                "flagged": 2,
            }
        ]
        assert day["results"][0]["patient"]["id"] == patient["id"]

        await review(client, found["id"])
        day = (await client.get(f"{API}/dashboard/summary")).json()["data"]
        assert day["results_total"] == 0

    async def test_every_role_is_given_what_it_needs(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        admin = (await client.get(f"{AUTH}/me")).json()["data"]
        granted = set(admin["permissions"])
        assert {"lab:read", "lab:update"} <= granted
        assert "lab:create" not in granted
        for role, expected in (
            ("doctor", {"lab:read", "lab:create", "lab:update"}),
            ("receptionist", {"lab:read", "lab:update"}),
            ("staff", set()),
        ):
            address = await invite_and_accept(client, role=role, outbox=outbox)
            await client.post(f"{AUTH}/logout")
            await sign_in(client, address)
            permissions = set((await client.get(f"{AUTH}/me")).json()["data"]["permissions"])
            assert {code for code in permissions if code.startswith("lab:")} == expected, role
            await client.post(f"{AUTH}/logout")
            await sign_in(client, admin["user"]["email"])

    async def test_read_only_staff_see_nothing_of_it(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="cbc")
        await become(client, clinic.admin)
        staff = await invite_and_accept(client, role="staff", outbox=outbox)
        await become(client, staff)

        for response in (
            await client.get(f"{API}/lab-orders"),
            await client.get(f"{API}/lab-orders/{found['id']}"),
            await client.get(f"{API}/lab-tests"),
            await cancel(client, found["id"]),
            await report(client, found["id"], findings="x"),
            await review(client, found["id"]),
        ):
            assert refusal(response)["status"] == 403

    async def test_another_clinic_finds_nothing(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, patient, notes = await in_the_room(client, outbox)
        found = await ordered(client, notes, test_code="cbc")
        await become(client, clinic.admin)
        await reported(client, found["id"], values=ANAEMIC)

        await client.post(f"{AUTH}/logout")
        await sign_up(client)

        for response in (
            await client.get(f"{API}/lab-orders/{found['id']}"),
            await report(client, found["id"], findings="x"),
            await client.delete(f"{API}/lab-orders/{found['id']}/result"),
            await cancel(client, found["id"]),
        ):
            refused = refusal(response)
            assert (refused["status"], refused["code"]) == (404, "LAB_NOT_FOUND")
        for params in ({}, {"patient_id": patient["id"]}, {"consultation_id": notes["id"]}):
            page = await listing(client, **params)
            assert (page["items"], page["total"]) == ([], 0)
            assert set(page["counts"].values()) == {0}
        listed = (await client.get(f"{API}/lab-tests")).json()["data"]
        assert all(test["times_ordered"] == 0 for test in listed["tests"])

    async def test_signed_out(self, client: AsyncClient) -> None:
        some_id = uuid.uuid4()
        for response in (
            await client.get(f"{API}/lab-orders"),
            await client.get(f"{API}/lab-tests"),
            await client.post(f"{API}/lab-orders", json={}),
            await client.get(f"{API}/lab-orders/{some_id}"),
            await client.put(f"{API}/lab-orders/{some_id}/result", json={}),
            await client.post(f"{API}/lab-orders/{some_id}/review"),
        ):
            assert response.status_code == 401

    async def test_a_malformed_id(self, client: AsyncClient) -> None:
        await sign_up(client)
        assert refusal(await client.get(f"{API}/lab-orders/not-an-id"))["status"] == 422
        assert (
            refusal(await client.get(f"{API}/lab-orders", params={"show": "all"}))["status"]
            == 422
        )
