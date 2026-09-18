"""Prescriptions: written with the notes, issued at the end of the visit,
corrected by replacement, and read and printed by the desk."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.models import Medicine
from tests.api.test_appointments import someone
from tests.api.test_clinic import invite_and_accept, sign_up
from tests.api.test_consultations import (
    a_clinic,
    become,
    finish,
    finished,
    linked_doctor,
    opened,
    read,
    save,
    saved,
)
from tests.api.test_patients import register
from tests.api.test_queue import lane_of, refusal, stepped, the_queue, today, walked_in
from tests.conftest import Outbox

API = "/api/v1"
LIST = Path(__file__).resolve().parents[2] / "app" / "data" / "medicines-nlem-2022.json"

FEVER = [
    {
        "medicine_name": "Paracetamol",
        "presentation": "Tablet 650 mg",
        "dose": "1-0-1",
        "timing": "after_food",
        "duration_days": 3,
    },
    {
        "medicine_name": "Cetirizine",
        "presentation": "Tablet 10 mg",
        "dose": "0-0-1",
        "timing": "bedtime",
        "duration_days": 5,
        "instructions": "May cause drowsiness",
    },
]


async def load_the_list(session: AsyncSession) -> None:
    listed = json.loads(LIST.read_text(encoding="utf-8"))["medicines"]
    rows = [
        {"id": uuid7(), "name": m["name"], "presentation": p, "source": "nlem-2022"}
        for m in listed
        for p in m["presentations"] or [None]
    ]
    await session.execute(insert(Medicine), rows)
    await session.commit()


async def visit(
    client: AsyncClient, outbox: Outbox, *, reason: str = "Fever"
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """A clinic, a patient with its doctor, and the doctor signed in with the
    notes open."""
    clinic = await a_clinic(client, outbox)
    patient = await register(client)
    entry = await walked_in(client, patient, clinic.doctor, reason=reason)
    await stepped(client, entry["id"], "start")
    await become(client, clinic.doctor_email)
    return clinic, entry, await opened(client, entry["id"])


async def issued(client: AsyncClient, notes: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Writes the prescription into the notes and finishes the visit."""
    notes = await saved(client, notes, medicines=fields.pop("medicines", FEVER), **fields)
    done = await finished(client, notes)
    standing: dict[str, Any] = done["prescriptions"][0]
    assert standing["status"] == "issued"
    return standing


async def correct(client: AsyncClient, prescription_id: str, **body: Any) -> Response:
    payload = {"medicines": FEVER[:1], "reason": "Wrong strength", **body}
    return await client.post(f"{API}/prescriptions/{prescription_id}/corrections", json=payload)


async def listing(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/prescriptions", params=params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


class TestWritingWithTheNotes:
    async def test_the_prescription_is_saved_with_the_notes_as_a_draft(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await visit(client, outbox)

        notes = await saved(
            client,
            notes,
            medicines=FEVER,
            prescription_instructions="  Plenty of fluids.  ",
        )

        assert notes["version"] == 2
        [draft] = notes["prescriptions"]
        assert draft["status"] == "draft"
        assert draft["number"] is None
        assert draft["instructions"] == "Plenty of fluids."
        assert [item["medicine_name"] for item in draft["items"]] == [
            "Paracetamol",
            "Cetirizine",
        ]
        assert draft["items"][1]["instructions"] == "May cause drowsiness"

        # A line still being typed has no dose yet, and saving it is fine.
        notes = await saved(client, notes, medicines=[{"medicine_name": "Amoxicillin"}])
        assert notes["prescriptions"][0]["items"] == [
            {
                "medicine_name": "Amoxicillin",
                "presentation": None,
                "dose": None,
                "timing": None,
                "duration_days": None,
                "instructions": None,
            }
        ]
        # Instructions were not sent, so they stay.
        assert notes["prescriptions"][0]["instructions"] == "Plenty of fluids."

    async def test_what_a_line_can_carry(self, client: AsyncClient, outbox: Outbox) -> None:
        _, _, notes = await visit(client, outbox)
        line = FEVER[0]

        for bad in (
            {**line, "medicine_name": "  "},
            {**line, "medicine_name": "x" * 201},
            {**line, "dose": "x" * 41},
            {**line, "duration_days": 0},
            {**line, "duration_days": 366},
            {**line, "timing": "whenever"},
            {**line, "strength": "500 mg"},
        ):
            assert (await save(client, notes, medicines=[bad])).status_code == 422, bad
        too_many = [line] * 31
        assert (await save(client, notes, medicines=too_many)).status_code == 422
        long_advice = "x" * 2001
        assert (
            await save(client, notes, prescription_instructions=long_advice)
        ).status_code == 422
        # Nothing got through.
        assert (await read(client, notes["id"])).json()["data"]["prescriptions"] == []

    async def test_the_desk_never_sees_a_draft(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await visit(client, outbox)
        notes = await saved(client, notes, medicines=FEVER)
        draft_id = notes["prescriptions"][0]["id"]
        await become(client, clinic.admin)
        receptionist = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, receptionist)

        assert (await listing(client))["total"] == 0
        assert (await client.get(f"{API}/prescriptions/{draft_id}")).status_code == 404
        assert (await client.get(f"{API}/prescriptions/{draft_id}/pdf")).status_code == 404


class TestIssuing:
    async def test_finishing_the_visit_issues_it_with_the_next_number(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, entry, notes = await visit(client, outbox)
        in_a_week = today() + dt.timedelta(days=7)

        prescription = await issued(
            client,
            notes,
            prescription_instructions="Rest.",
            follow_up_date=in_a_week.isoformat(),
        )

        assert prescription["number"] == "RX-000001"
        assert prescription["issued_at"] is not None
        assert prescription["follow_up_date"] == in_a_week.isoformat()
        assert prescription["instructions"] == "Rest."
        # The queue carries it, for the desk to print as the patient leaves.
        lane = lane_of(await the_queue(client), clinic.doctor)
        assert lane["done"][0]["id"] == entry["id"]
        assert lane["done"][0]["prescription_id"] == prescription["id"]

    async def test_numbers_run_on_across_visits_and_start_afresh_per_clinic(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await visit(client, outbox)
        first = await issued(client, notes)
        await become(client, clinic.admin)
        entry = await walked_in(client, await someone(client, "Bina"), clinic.doctor)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)
        second = await issued(client, await opened(client, entry["id"]))
        assert (first["number"], second["number"]) == ("RX-000001", "RX-000002")

        await client.post(f"{API}/auth/logout")
        _, _, elsewhere = await visit(client, outbox)
        assert (await issued(client, elsewhere))["number"] == "RX-000001"

    async def test_a_line_without_a_dose_keeps_the_visit_open(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, entry, notes = await visit(client, outbox)
        notes = await saved(
            client, notes, medicines=[FEVER[0], {"medicine_name": "Amoxicillin"}]
        )

        refused = refusal(await finish(client, notes))

        assert refused["status"] == 422
        assert refused["fields"] == {"medicines.1.dose": "Say how much to take."}
        assert refused["message"] == "Medicine 2 on the prescription has no dose yet."
        kept = (await read(client, notes["id"])).json()["data"]
        assert kept["status"] == "draft"
        assert kept["prescriptions"][0]["status"] == "draft"
        lane = lane_of(await the_queue(client), clinic.doctor)
        assert lane["now_seeing"]["id"] == entry["id"]

    async def test_an_emptied_prescription_is_not_issued(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await visit(client, outbox)
        notes = await saved(client, notes, medicines=FEVER)
        notes = await saved(client, notes, medicines=[])

        done = await finished(client, notes)

        assert done["prescriptions"] == []

    async def test_advice_alone_is_issued_and_a_prescription_alone_finishes_a_visit(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await visit(client, outbox)
        notes = await saved(client, notes, chief_complaint=None)
        assert notes["chief_complaint"] is None

        prescription = await issued(
            client,
            notes,
            medicines=[],
            prescription_instructions="Steam inhalation twice a day.",
        )

        assert prescription["items"] == []
        assert prescription["instructions"] == "Steam inhalation twice a day."

    async def test_a_finished_visits_prescription_is_only_changed_by_correction(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await visit(client, outbox)
        await issued(client, notes)
        current = (await read(client, notes["id"])).json()["data"]

        refused = refusal(await save(client, current, medicines=[]))

        assert refused["code"] == "CONSULT_ALREADY_COMPLETED"


class TestCorrections:
    async def test_a_correction_replaces_the_prescription_and_keeps_both(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await visit(client, outbox)
        in_a_week = today() + dt.timedelta(days=7)
        original = await issued(client, notes, follow_up_date=in_a_week.isoformat())

        response = await correct(
            client,
            original["id"],
            medicines=[{**FEVER[0], "presentation": "Tablet 500 mg"}],
            instructions="Fluids.",
            reason="Wrong strength written",
        )

        assert response.status_code == 201, response.text
        replacement = response.json()["data"]
        assert replacement["number"] == "RX-000002"
        assert replacement["status"] == "issued"
        assert replacement["replaces"] == {"id": original["id"], "number": "RX-000001"}
        assert replacement["correction_reason"] == "Wrong strength written"
        assert replacement["follow_up_date"] == in_a_week.isoformat()
        assert replacement["items"][0]["presentation"] == "Tablet 500 mg"
        assert replacement["can_correct"] is True

        old = (await client.get(f"{API}/prescriptions/{original['id']}")).json()["data"]
        assert old["status"] == "replaced"
        assert old["replaced_by"] == {"id": replacement["id"], "number": "RX-000002"}
        assert old["can_correct"] is False
        # The visit shows the standing one first and what it replaced after.
        visit_record = (await read(client, notes["id"])).json()["data"]
        assert [p["number"] for p in visit_record["prescriptions"]] == [
            "RX-000002",
            "RX-000001",
        ]

    async def test_a_replaced_prescription_is_not_corrected_again(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await visit(client, outbox)
        original = await issued(client, notes)
        assert (await correct(client, original["id"])).status_code == 201

        refused = refusal(await correct(client, original["id"]))

        assert refused["status"] == 409
        assert refused["code"] == "RX_ALREADY_REPLACED"
        assert "replaced by RX-000002" in refused["message"]

    async def test_two_corrections_at_once_leave_one_standing(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await visit(client, outbox)
        original = await issued(client, notes)

        answers = await asyncio.gather(
            correct(client, original["id"]), correct(client, original["id"])
        )

        assert sorted(answer.status_code for answer in answers) == [201, 409]
        record = (await read(client, notes["id"])).json()["data"]
        assert [p["status"] for p in record["prescriptions"]] == ["issued", "replaced"]

    async def test_what_a_correction_needs(self, client: AsyncClient, outbox: Outbox) -> None:
        _, _, notes = await visit(client, outbox)
        original = await issued(client, notes)

        assert (await correct(client, original["id"], medicines=[])).status_code == 422
        assert (await correct(client, original["id"], reason="  ")).status_code == 422
        no_dose = refusal(
            await correct(client, original["id"], medicines=[{"medicine_name": "Amoxicillin"}])
        )
        assert no_dose["fields"] == {"medicines.0.dose": "Say how much to take."}
        still = (await client.get(f"{API}/prescriptions/{original['id']}")).json()["data"]
        assert still["status"] == "issued"

    async def test_only_the_doctor_who_wrote_it_corrects_it(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, _, notes = await visit(client, outbox)
        original = await issued(client, notes)
        await become(client, clinic.admin)
        colleague, _ = await linked_doctor(client, outbox, first_name="Vikram")
        receptionist = await invite_and_accept(client, role="receptionist", outbox=outbox)

        # The admin and the desk have no way to write prescriptions at all.
        assert (await correct(client, original["id"])).status_code == 403
        await become(client, receptionist)
        assert (await correct(client, original["id"])).status_code == 403
        # A colleague may read it, but it is not theirs to change.
        await become(client, colleague)
        theirs = (await client.get(f"{API}/prescriptions/{original['id']}")).json()["data"]
        assert theirs["can_correct"] is False
        refused = refusal(await correct(client, original["id"]))
        assert refused["status"] == 403
        assert refused["code"] == "RX_NOT_PRESCRIBER"


class TestReadingAndPrinting:
    async def test_the_desk_reads_lists_and_prints_what_was_issued(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        clinic, entry, notes = await visit(client, outbox)
        prescription = await issued(client, notes)
        await become(client, clinic.admin)
        receptionist = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await become(client, receptionist)

        found = (await client.get(f"{API}/prescriptions/{prescription['id']}")).json()["data"]
        assert found["number"] == "RX-000001"
        assert found["doctor"]["display_name"] == clinic.doctor["display_name"]
        assert found["clinic"]["name"]
        assert found["patient"]["id"] == entry["patient"]["id"]
        assert found["can_correct"] is False

        mine = await listing(client, patient_id=entry["patient"]["id"])
        assert mine["total"] == 1
        assert mine["items"][0]["medicines"] == ["Paracetamol", "Cetirizine"]

        pdf = await client.get(f"{API}/prescriptions/{prescription['id']}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.headers["content-disposition"] == 'inline; filename="RX-000001.pdf"'
        assert pdf.content.startswith(b"%PDF")

    async def test_a_replaced_copy_still_prints(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        _, _, notes = await visit(client, outbox)
        original = await issued(client, notes)
        await correct(client, original["id"])

        pdf = await client.get(f"{API}/prescriptions/{original['id']}/pdf")

        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")

    async def test_awkward_words_print(self, client: AsyncClient, outbox: Outbox) -> None:
        _, _, notes = await visit(client, outbox)
        prescription = await issued(
            client,
            notes,
            medicines=[
                {
                    "medicine_name": "Iron <sucrose> & folic acid",
                    "presentation": "Tablet 100 mg (A) + 500 mcg (B)",
                    "dose": "1-0-0",
                    "instructions": "With orange juice, not tea\nStop if stools turn black",
                }
            ]
            * 30,
            prescription_instructions="Line one\n<b>not markup</b> & more",
        )

        pdf = await client.get(f"{API}/prescriptions/{prescription['id']}/pdf")

        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")

    async def test_who_cannot_reach_them(self, client: AsyncClient, outbox: Outbox) -> None:
        clinic, _, notes = await visit(client, outbox)
        prescription = await issued(client, notes)
        await become(client, clinic.admin)
        staff = await invite_and_accept(client, role="staff", outbox=outbox)
        await become(client, staff)
        assert (await client.get(f"{API}/prescriptions")).status_code == 403
        assert (
            await client.get(f"{API}/prescriptions/{prescription['id']}")
        ).status_code == 403

        await client.post(f"{API}/auth/logout")
        await sign_up(client)
        for path in ("", "/pdf"):
            answer = await client.get(f"{API}/prescriptions/{prescription['id']}{path}")
            assert answer.status_code == 404
        assert (await correct(client, prescription["id"])).status_code == 403
        assert (await listing(client))["total"] == 0
        assert (await client.get(f"{API}/prescriptions/not-an-id")).status_code == 422
        unknown = "0192f0a1-0000-7000-8000-000000000000"
        assert (await client.get(f"{API}/prescriptions/{unknown}")).status_code == 404


class TestTheMedicineList:
    def test_the_published_list_as_loaded(self) -> None:
        listed = json.loads(LIST.read_text(encoding="utf-8"))
        medicines = listed["medicines"]
        assert len(medicines) == 376
        names = [m["name"].lower() for m in medicines]
        assert len(names) == len(set(names))
        for medicine in medicines:
            assert medicine["name"] == medicine["name"].strip()
            for presentation in medicine["presentations"]:
                assert presentation == presentation.strip() and presentation
                assert "Section" not in presentation and not presentation.endswith("+")
        by_name = {m["name"]: m["presentations"] for m in medicines}
        assert "Tablet 500 mg" in by_name["Paracetamol"]
        assert "Capsule 500 mg" in by_name["Amoxicillin"]
        assert "Tablet 500 mg" in by_name["Metformin"]
        assert by_name["Hydrochlorothiazide"] == [
            "Tablet 12.5 mg",
            "Tablet 25 mg",
            "Tablet 50 mg",
        ]

    async def test_suggestions_start_with_what_was_typed(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        await load_the_list(session)
        await visit(client, outbox)

        found = (await client.get(f"{API}/medicines", params={"q": "parace"})).json()["data"]
        assert found[0] == {
            "name": "Paracetamol",
            "presentation": "Tablet 500 mg",
            "source": "list",
            "times_prescribed": 0,
        }
        # The forms a clinic writes most come before injections.
        forms = [s["presentation"] for s in found if s["name"] == "Paracetamol"]
        assert forms.index("Tablet 650 mg") < forms.index("Injection 150 mg/mL")
        # A slip of the finger still finds it.
        slipped = (await client.get(f"{API}/medicines", params={"q": "paracetmol"})).json()
        assert slipped["data"][0]["name"] == "Paracetamol"
        nothing = (await client.get(f"{API}/medicines", params={"q": "zzqx"})).json()["data"]
        assert nothing == []
        # What is typed is matched as typed, never as a wildcard.
        for typed in ("%%", "__", "%_%"):
            found = (await client.get(f"{API}/medicines", params={"q": typed})).json()["data"]
            assert found == [], typed

    async def test_the_clinics_own_prescribing_comes_first(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        await load_the_list(session)
        clinic, _, notes = await visit(client, outbox)
        brand = {"medicine_name": "Paracip 650", "dose": "1-0-1"}
        await issued(client, notes, medicines=[brand])
        # A draft somewhere else does not count as having prescribed it.
        await become(client, clinic.admin)
        entry = await walked_in(client, await someone(client, "Bina"), clinic.doctor)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)
        await saved(client, await opened(client, entry["id"]), medicines=[brand])

        found = (await client.get(f"{API}/medicines", params={"q": "parac"})).json()["data"]

        assert found[0] == {
            "name": "Paracip 650",
            "presentation": None,
            "source": "clinic",
            "times_prescribed": 1,
        }
        assert found[1]["name"] == "Paracetamol"

        # Another clinic's habits are its own.
        await client.post(f"{API}/auth/logout")
        await visit(client, outbox)
        elsewhere = (await client.get(f"{API}/medicines", params={"q": "parac"})).json()["data"]
        assert all(s["source"] == "list" for s in elsewhere)

    async def test_who_asks_and_how(self, client: AsyncClient, outbox: Outbox) -> None:
        clinic, _, _ = await visit(client, outbox)
        assert (await client.get(f"{API}/medicines", params={"q": "p"})).status_code == 422
        assert (await client.get(f"{API}/medicines")).status_code == 422
        long = "x" * 61
        assert (await client.get(f"{API}/medicines", params={"q": long})).status_code == 422
        await become(client, clinic.admin)
        assert (await client.get(f"{API}/medicines", params={"q": "para"})).status_code == 403
