"""The first page after signing in: the clinic's day for the desk and the
administrator, a doctor's own day for a doctor."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Consultation, QueueEntry
from tests.api.test_appointments import doctor_with_hours
from tests.api.test_clinic import AUTH, invite_and_accept, sign_in, sign_up
from tests.api.test_consultations import a_clinic, become, finished, opened, saved
from tests.api.test_patients import register
from tests.api.test_queue import booked_today, check_in, stepped, today, walked_in
from tests.api.test_vitals import taken
from tests.conftest import Outbox

API = "/api/v1"

PEOPLE = iter(range(10_000, 99_999))


async def patient(client: AsyncClient, first_name: str) -> dict[str, Any]:
    """Someone new, told apart from everyone else here by phone and birthday,
    so the duplicate check has no reason to stop them."""
    n = next(PEOPLE)
    born = dt.date(1960, 1, 1) + dt.timedelta(days=n % 9_000)
    return await register(
        client, first_name=first_name, phone=f"98200{n:05d}", date_of_birth=born.isoformat()
    )


async def summary(client: AsyncClient) -> dict[str, Any]:
    response = await client.get(f"{API}/dashboard/summary")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


def lane_for(day: dict[str, Any], doctor: dict[str, Any]) -> dict[str, Any]:
    return next(lane for lane in day["lanes"] if lane["doctor"]["id"] == doctor["id"])


async def waited(session: AsyncSession, entry: dict[str, Any], minutes: int) -> None:
    """Moves an arrival back, as if they had been sitting there a while."""
    await session.execute(
        update(QueueEntry)
        .where(QueueEntry.id == uuid.UUID(entry["id"]))
        .values(checked_in_at=QueueEntry.checked_in_at - dt.timedelta(minutes=minutes))
    )
    await session.commit()


class TestTheClinicsDay:
    async def test_the_counts_add_up(self, client: AsyncClient, session: AsyncSession) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        # Booked, half an hour apart since a doctor's bookings may not overlap:
        # one here already, one late, one later on, one cancelled, one who
        # never came.
        here = await patient(client, "Asha")
        await check_in(client, await booked_today(session, client, here, doctor, at="00:30"))
        late = await patient(client, "Bina")
        await booked_today(session, client, late, doctor, at="00:05")
        later = await patient(client, "Chitra")
        await booked_today(session, client, later, doctor, at="23:30")
        dropped = await patient(client, "Dev")
        await booked_today(session, client, dropped, doctor, at="01:00", status="cancelled")
        missed = await patient(client, "Esha")
        await booked_today(session, client, missed, doctor, at="01:30", status="no_show")
        # Walk-ins: one seen, one who left, one still waiting.
        seen = await walked_in(client, await patient(client, "Farid"), doctor)
        await stepped(client, seen["id"], "start")
        await stepped(client, seen["id"], "complete")
        gone = await walked_in(client, await patient(client, "Gita"), doctor)
        await stepped(client, gone["id"], "no-show")
        await walked_in(client, await patient(client, "Hari"), doctor)

        day = await summary(client)

        assert day["view"] == "clinic"
        assert day["date"] == today().isoformat()
        assert day["counts"] == {
            "booked": 4,
            "to_come": 2,
            "late": 1,
            "walk_ins": 1,
            "waiting": 2,
            "with_doctor": 0,
            "seen": 1,
            "no_shows": 2,
        }
        assert [
            (arrival["patient"]["full_name"], arrival["is_late"]) for arrival in day["arrivals"]
        ] == [("Bina Deshmukh", True), ("Chitra Deshmukh", False)]
        assert day["arrivals_total"] == 2

    async def test_each_doctors_line(self, client: AsyncClient, session: AsyncSession) -> None:
        await sign_up(client)
        busy = await doctor_with_hours(client, first_name="Busy")
        free = await doctor_with_hours(client, first_name="Free")
        away = await doctor_with_hours(client, first_name="Away")
        leave = await client.post(
            f"{API}/doctors/{away['id']}/leaves",
            json={"starts_on": today().isoformat(), "reason": "Conference"},
        )
        assert leave.status_code == 201, leave.text

        inside = await walked_in(client, await patient(client, "Inside"), busy)
        await stepped(client, inside["id"], "start")
        first = await walked_in(client, await patient(client, "First"), busy)
        second = await walked_in(client, await patient(client, "Second"), busy)
        await waited(session, first, 50)
        await waited(session, second, 20)

        day = await summary(client)

        line = lane_for(day, busy)
        assert line["now_seeing"]["token"] == inside["token"]
        assert line["waiting"] == 2
        assert line["longest_wait_minutes"] == 50
        assert line["next"]["token"] == first["token"]
        assert lane_for(day, free)["now_seeing"] is None
        assert lane_for(day, free)["waiting"] == 0
        assert lane_for(day, away)["closed"].startswith("On leave")

    async def test_the_waiting_room_puts_urgent_first_then_the_longest_wait(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        long = await walked_in(client, await patient(client, "Long"), doctor)
        short = await walked_in(client, await patient(client, "Short"), doctor)
        urgent = await walked_in(
            client, await patient(client, "Urgent"), doctor, priority="urgent"
        )
        await waited(session, long, 40)
        await waited(session, short, 5)
        await taken(client, short["id"], systolic_mmhg=150, diastolic_mmhg=95)

        day = await summary(client)

        assert [entry["entry_id"] for entry in day["waiting"]] == [
            urgent["id"],
            long["id"],
            short["id"],
        ]
        assert day["waiting_total"] == 3
        assert day["without_vitals"] == 2
        with_vitals = day["waiting"][2]["vitals"]
        assert with_vitals["flags"] == {"blood_pressure": "high"}
        # The line runs urgent first too, so the urgent one is next.
        assert lane_for(day, doctor)["next"]["entry_id"] == urgent["id"]

    async def test_a_quiet_day(self, client: AsyncClient) -> None:
        await sign_up(client)
        day = await summary(client)
        assert day["view"] == "clinic"
        assert day["lanes"] == []
        assert day["waiting"] == []
        assert day["arrivals"] == []
        assert day["due_back"] == []
        assert set(day["counts"].values()) == {0}


class TestPatientsAskedBack:
    async def asked_back(
        self, client: AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> tuple[Any, dict[str, Any]]:
        """A patient the doctor saw and asked to come back today. The admin
        is signed in afterwards."""
        clinic = await a_clinic(client, outbox)
        person = await patient(client, "Ravi")
        entry = await walked_in(client, person, clinic.doctor)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)
        notes = await saved(client, await opened(client, entry["id"]), chief_complaint="BP")
        await finished(client, notes)
        # Written straight in: a follow-up date can only be set in the future,
        # and this one has to have arrived.
        await session.execute(
            update(Consultation)
            .where(Consultation.id == uuid.UUID(notes["id"]))
            .values(
                follow_up_date=today(),
                started_at=Consultation.started_at - dt.timedelta(days=7),
            )
        )
        # The visit itself was a week ago too, not a place in today's queue.
        await session.execute(
            update(QueueEntry)
            .where(QueueEntry.id == uuid.UUID(entry["id"]))
            .values(token_date=today() - dt.timedelta(days=7))
        )
        await session.commit()
        await become(client, clinic.admin)
        return clinic, person

    async def test_from_not_booked_to_booked_to_here(
        self, client: AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        clinic, person = await self.asked_back(client, session, outbox)

        [due] = (await summary(client))["due_back"]
        assert due["patient"]["id"] == person["id"]
        assert due["doctor"]["id"] == clinic.doctor["id"]
        assert due["state"] == "not_booked"
        assert due["booked_for"] is None

        appointment = await booked_today(session, client, person, clinic.doctor, at="23:30")
        [due] = (await summary(client))["due_back"]
        assert (due["state"], due["booked_for"]) == ("booked", "23:30:00")

        await check_in(client, appointment)
        [due] = (await summary(client))["due_back"]
        assert due["state"] == "here"

    async def test_a_visit_since_answers_it(
        self, client: AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        clinic, person = await self.asked_back(client, session, outbox)
        # They came back early, three days ago.
        entry = await walked_in(client, person, clinic.doctor)
        await stepped(client, entry["id"], "start")
        await become(client, clinic.doctor_email)
        notes = await saved(client, await opened(client, entry["id"]), chief_complaint="BP")
        await finished(client, notes)
        await session.execute(
            update(Consultation)
            .where(Consultation.id == uuid.UUID(notes["id"]))
            .values(started_at=Consultation.started_at - dt.timedelta(days=3))
        )
        await session.execute(
            update(QueueEntry)
            .where(QueueEntry.id == uuid.UUID(entry["id"]))
            .values(token_date=today() - dt.timedelta(days=3))
        )
        await session.commit()
        await become(client, clinic.admin)

        assert (await summary(client))["due_back"] == []

    async def test_a_visit_today_is_them_coming_back(
        self, client: AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        clinic, person = await self.asked_back(client, session, outbox)
        entry = await walked_in(client, person, clinic.doctor)
        await stepped(client, entry["id"], "start")
        await stepped(client, entry["id"], "complete")

        [due] = (await summary(client))["due_back"]
        assert due["state"] == "seen"


class TestADoctorsOwnDay:
    async def test_only_their_line_and_their_open_notes(
        self, client: AsyncClient, session: AsyncSession, outbox: Outbox
    ) -> None:
        clinic = await a_clinic(client, outbox)
        colleague = await doctor_with_hours(client, first_name="Colleague")
        await walked_in(client, await patient(client, "Theirs"), colleague)
        # An earlier visit whose notes were left open, and the one in the
        # room now, whose notes are being written.
        left = await walked_in(client, await patient(client, "Left"), clinic.doctor)
        await stepped(client, left["id"], "start")
        now = await walked_in(client, await patient(client, "Now"), clinic.doctor)
        await walked_in(client, await patient(client, "Next"), clinic.doctor)
        await become(client, clinic.doctor_email)
        await saved(client, await opened(client, left["id"]), chief_complaint="Cough")
        await become(client, clinic.admin)
        await stepped(client, left["id"], "complete")
        await stepped(client, now["id"], "start")
        await become(client, clinic.doctor_email)
        await opened(client, now["id"])

        day = await summary(client)

        assert day["view"] == "doctor"
        assert [lane["doctor"]["id"] for lane in day["lanes"]] == [clinic.doctor["id"]]
        assert day["counts"]["waiting"] == 1
        assert [entry["patient"]["full_name"] for entry in day["waiting"]] == ["Next Deshmukh"]
        assert [item["patient"]["full_name"] for item in day["unfinished"]] == ["Left Deshmukh"]
        assert day["unfinished"][0]["chief_complaint"] == "Cough"
        assert day["unfinished_total"] == 1
        # The clinic view never lists anyone's open notes.
        await become(client, clinic.admin)
        assert (await summary(client))["unfinished"] == []

    async def test_a_doctors_account_with_no_profile(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="doctor", outbox=outbox)
        await client.post(f"{AUTH}/logout")
        await sign_in(client, address)

        day = await summary(client)

        assert day["view"] == "unlinked"
        assert day["lanes"] == []


class TestWhoSeesIt:
    async def test_every_role_sees_a_day(self, client: AsyncClient, outbox: Outbox) -> None:
        await sign_up(client)
        admin = (await client.get(f"{AUTH}/me")).json()["data"]["user"]["email"]
        for role in ("receptionist", "staff"):
            address = await invite_and_accept(client, role=role, outbox=outbox)
            await client.post(f"{AUTH}/logout")
            await sign_in(client, address)
            assert (await summary(client))["view"] == "clinic", role
            await client.post(f"{AUTH}/logout")
            await sign_in(client, admin)

    async def test_another_clinics_day_is_not_counted(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        await walked_in(client, await patient(client, "Elsewhere"), doctor)

        await client.post(f"{AUTH}/logout")
        await sign_up(client)

        day = await summary(client)
        assert day["lanes"] == []
        assert day["counts"]["waiting"] == 0

    async def test_signed_out(self, client: AsyncClient) -> None:
        assert (await client.get(f"{API}/dashboard/summary")).status_code == 401
