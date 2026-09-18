"""The day's queue: checking in, walk-ins, and a patient's way through the door.

Appointments for today are written straight to the table at a fixed time of
the clinic's day, because the API only books times still ahead and a test
run at four in the afternoon would otherwise have nothing left to book.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, QueueEntry
from tests.api.test_appointments import (
    KOLKATA,
    act,
    book,
    clinic_day,
    clinic_id,
    doctor_with_hours,
    someone,
)
from tests.api.test_clinic import invite_and_accept, sign_in, sign_up, someone_else
from tests.api.test_doctors import add as add_doctor
from tests.api.test_doctors import set_schedule
from tests.api.test_patients import register
from tests.conftest import Outbox

API = "/api/v1"
AUTH = "/api/v1/auth"


def today() -> dt.date:
    return dt.datetime.now(KOLKATA).date()


async def booked_today(
    session: AsyncSession,
    client: AsyncClient,
    patient: dict[str, Any],
    doctor: dict[str, Any],
    *,
    at: str = "09:00",
    status: str = "scheduled",
    minutes: int = 15,
) -> str:
    """An appointment at a wall-clock time today, whatever the time is now."""
    hours, mins = (int(part) for part in at.split(":"))
    starts = dt.datetime.combine(today(), dt.time(hours, mins), tzinfo=KOLKATA)
    appointment = Appointment(
        organization_id=await clinic_id(client),
        patient_id=uuid.UUID(patient["id"]),
        doctor_id=uuid.UUID(doctor["id"]),
        scheduled_start=starts,
        scheduled_end=starts + dt.timedelta(minutes=minutes),
        appointment_type="consultation",
        source="desk",
        status=status,
    )
    session.add(appointment)
    await session.commit()
    return str(appointment.id)


async def check_in(client: AsyncClient, appointment_id: str, **body: Any) -> Response:
    return await client.post(f"{API}/appointments/{appointment_id}/check-in", json=body)


async def checked_in(client: AsyncClient, appointment_id: str, **body: Any) -> dict[str, Any]:
    response = await check_in(client, appointment_id, **body)
    assert response.status_code == 201, response.text
    entry: dict[str, Any] = response.json()["data"]
    return entry


async def walk_in(
    client: AsyncClient, patient: dict[str, Any], doctor: dict[str, Any], **body: Any
) -> Response:
    return await client.post(
        f"{API}/queue/walk-in",
        json={"patient_id": patient["id"], "doctor_id": doctor["id"], **body},
    )


async def walked_in(
    client: AsyncClient, patient: dict[str, Any], doctor: dict[str, Any], **body: Any
) -> dict[str, Any]:
    response = await walk_in(client, patient, doctor, **body)
    assert response.status_code == 201, response.text
    entry: dict[str, Any] = response.json()["data"]
    return entry


async def step(client: AsyncClient, entry_id: str, action: str) -> Response:
    return await client.post(f"{API}/queue/{entry_id}/{action}")


async def stepped(client: AsyncClient, entry_id: str, action: str) -> dict[str, Any]:
    response = await step(client, entry_id, action)
    assert response.status_code == 200, response.text
    entry: dict[str, Any] = response.json()["data"]
    return entry


async def the_queue(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/queue", params=params)
    assert response.status_code == 200, response.text
    queue: dict[str, Any] = response.json()["data"]
    return queue


def lane_of(queue: dict[str, Any], doctor: dict[str, Any]) -> dict[str, Any]:
    return next(lane for lane in queue["lanes"] if lane["doctor"]["id"] == doctor["id"])


async def appointment(client: AsyncClient, appointment_id: str) -> dict[str, Any]:
    response = await client.get(f"{API}/appointments/{appointment_id}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["data"]
    return found


def refusal(response: Response) -> dict[str, Any]:
    assert response.status_code >= 400, response.text
    error: dict[str, Any] = response.json()["error"]
    error["status"] = response.status_code
    return error


class TestCheckingIn:
    async def test_arriving_gives_a_token_and_moves_the_appointment_along(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        asha = await someone(client, "Asha")
        bina = await someone(client, "Bina")
        first = await booked_today(session, client, asha, doctor, at="09:00")
        second = await booked_today(session, client, bina, doctor, at="09:30")

        one = await checked_in(client, first)
        two = await checked_in(client, second)

        assert (one["token"], two["token"]) == (1, 2)
        assert one["status"] == "waiting"
        assert one["appointment"]["id"] == first
        assert one["appointment"]["start_time"] == "09:00:00"
        assert (one["position"], two["position"]) == (1, 2)

        booked = await appointment(client, first)
        assert booked["status"] == "waiting"
        assert booked["queue_token"] == 1
        assert booked["is_today"] is True
        last = booked["history"][-1]
        assert (last["event"], last["from_status"], last["to_status"]) == (
            "checked_in",
            "scheduled",
            "waiting",
        )
        assert last["detail"] == "Token 1"

    async def test_each_doctor_counts_from_one(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        iyer = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        rao = await doctor_with_hours(client, first_name="Vikram", last_name="Rao")

        await walked_in(client, await someone(client, "Asha"), iyer)
        await walked_in(client, await someone(client, "Bina"), iyer)
        with_rao = await walked_in(client, await someone(client, "Chitra"), rao)

        assert with_rao["token"] == 1

    async def test_checking_in_twice_says_which_token_they_have(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await booked_today(session, client, await register(client), doctor)
        await checked_in(client, made)

        error = refusal(await check_in(client, made))

        assert error["status"] == 409
        assert error["code"] == "QUEUE_ALREADY_CHECKED_IN"
        assert error["message"] == "Already checked in, token 1."

    async def test_four_desks_checking_the_same_person_in_get_one_place(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await booked_today(session, client, await register(client), doctor)

        answers = await asyncio.gather(*(check_in(client, made) for _ in range(4)))

        assert sorted(answer.status_code for answer in answers) == [201, 409, 409, 409]
        lane = lane_of(await the_queue(client), doctor)
        assert [entry["token"] for entry in lane["waiting"]] == [1]

    async def test_desks_checking_in_at_once_never_share_a_token(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        people = [await someone(client, name) for name in ("Asha", "Bina", "Chitra", "Deepa")]

        answers = await asyncio.gather(*(walk_in(client, person, doctor) for person in people))

        assert all(answer.status_code == 201 for answer in answers), [a.text for a in answers]
        assert sorted(answer.json()["data"]["token"] for answer in answers) == [1, 2, 3, 4]

    async def test_an_appointment_on_another_day(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await book(
            client, await register(client), doctor, date=clinic_day(1).isoformat()
        )

        error = refusal(await check_in(client, made["id"]))

        assert error["status"] == 422
        assert error["code"] == "QUEUE_NOT_TODAY"
        assert "not today" in error["message"]
        assert (await appointment(client, made["id"]))["status"] == "scheduled"

    async def test_a_cancelled_appointment(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await booked_today(
            session, client, await register(client), doctor, status="cancelled"
        )

        error = refusal(await check_in(client, made))

        assert error["status"] == 409
        assert error["message"] == "This appointment was cancelled."

    async def test_an_archived_patient(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        made = await booked_today(session, client, patient, doctor)
        await client.post(f"{API}/patients/{patient['id']}/archive")

        error = refusal(await check_in(client, made))

        assert error["status"] == 409
        assert error["code"] == "PATIENT_ARCHIVED"
        assert "before checking them in" in error["message"]

    async def test_a_doctor_on_leave_today(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await booked_today(session, client, await register(client), doctor)
        leave = await client.post(
            f"{API}/doctors/{doctor['id']}/leaves",
            json={"starts_on": today().isoformat(), "reason": "Unwell"},
        )
        assert leave.status_code == 201, leave.text

        error = refusal(await check_in(client, made))

        assert error["status"] == 409
        assert error["message"] == f"{doctor['display_name']} is on leave today."
        lane = lane_of(await the_queue(client), doctor)
        assert lane["closed"] == "On leave today (Unwell)"

    async def test_a_doctor_with_no_clinic_today(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add_doctor(client)
        tomorrow = (today().weekday() + 1) % 7
        response = await set_schedule(
            client,
            doctor["id"],
            [{"day_of_week": tomorrow, "start_time": "09:00", "end_time": "13:00"}],
        )
        assert response.status_code == 200, response.text

        error = refusal(await walk_in(client, await register(client), doctor))

        assert error["status"] == 409
        assert "clinic" in error["message"]
        # And with nobody booked, the desk is not shown an empty lane for them.
        queue = await the_queue(client)
        assert all(lane["doctor"]["id"] != doctor["id"] for lane in queue["lanes"])

    async def test_a_doctor_who_has_been_stood_down(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        await client.post(f"{API}/doctors/{doctor['id']}/deactivate")

        error = refusal(await walk_in(client, await register(client), doctor))

        assert error["status"] == 409
        assert error["code"] == "DOCTOR_INACTIVE"

    async def test_a_checked_in_appointment_can_no_longer_be_moved_or_cancelled(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await booked_today(session, client, await register(client), doctor)
        await checked_in(client, made)

        cancelled = refusal(await act(client, made, "cancel"))
        moved = refusal(
            await client.patch(f"{API}/appointments/{made}", json={"start_time": "10:00"})
        )

        assert cancelled["status"] == moved["status"] == 409
        assert cancelled["message"] == "The patient has checked in and is in the queue."


class TestWalkIns:
    async def test_a_walk_in_joins_with_no_appointment(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)

        entry = await walked_in(
            client, await register(client), doctor, reason="  Fever since last night  "
        )

        assert entry["token"] == 1
        assert entry["appointment"] is None
        assert entry["reason"] == "Fever since last night"
        assert entry["position"] == 1

    async def test_somebody_already_in_a_line_is_not_put_in_another(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        iyer = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        rao = await doctor_with_hours(client, first_name="Vikram", last_name="Rao")
        asha = await someone(client, "Asha")
        await walked_in(client, asha, iyer)

        error = refusal(await walk_in(client, asha, rao))

        assert error["status"] == 409
        assert error["code"] == "QUEUE_ALREADY_CHECKED_IN"
        assert error["message"] == "Asha is already in the queue for Dr Ananya Iyer, token 1."

    async def test_once_seen_they_can_join_another_doctors_line(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        iyer = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        rao = await doctor_with_hours(client, first_name="Vikram", last_name="Rao")
        asha = await someone(client, "Asha")
        first = await walked_in(client, asha, iyer)
        await stepped(client, first["id"], "start")
        await stepped(client, first["id"], "complete")

        assert (await walked_in(client, asha, rao))["token"] == 1

    async def test_someone_booked_for_later_is_checked_in_against_the_booking(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        asha = await someone(client, "Asha")
        await booked_today(session, client, asha, doctor, at="12:30")

        error = refusal(await walk_in(client, asha, doctor))

        assert error["status"] == 409
        assert error["code"] == "QUEUE_HAS_APPOINTMENT"
        assert "12:30 pm today" in error["message"]

    async def test_a_reason_longer_than_the_field_is_refused(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)

        error = refusal(await walk_in(client, await register(client), doctor, reason="x" * 201))

        assert error["status"] == 422
        assert "reason" in error["fields"]

    async def test_an_unknown_priority_is_refused(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)

        error = refusal(
            await walk_in(client, await register(client), doctor, priority="whenever")
        )

        assert error["status"] == 422


class TestThroughTheDoor:
    async def test_called_seen_and_finished(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await booked_today(session, client, await register(client), doctor)
        entry = await checked_in(client, made)

        called = await stepped(client, entry["id"], "call")
        assert called["status"] == "called" and called["called_at"]
        assert lane_of(await the_queue(client), doctor)["called"]["id"] == entry["id"]

        started = await stepped(client, entry["id"], "start")
        assert started["status"] == "in_consultation"
        assert (await appointment(client, made))["status"] == "in_consultation"
        assert lane_of(await the_queue(client), doctor)["now_seeing"]["id"] == entry["id"]

        finished = await stepped(client, entry["id"], "complete")
        assert finished["status"] == "completed"
        booked = await appointment(client, made)
        assert booked["status"] == "completed"
        # Written straight to the table, so its history starts at arrival.
        assert [line["event"] for line in booked["history"]] == [
            "checked_in",
            "started",
            "seen",
        ]

        lane = lane_of(await the_queue(client), doctor)
        assert lane["now_seeing"] is None
        assert lane["seen_count"] == 1
        assert [done["id"] for done in lane["done"]] == [entry["id"]]

    async def test_a_doctor_can_wave_in_whoever_is_waiting(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        entry = await walked_in(client, await register(client), doctor)

        started = await stepped(client, entry["id"], "start")

        assert started["status"] == "in_consultation"
        assert started["called_at"] == started["started_at"]

    async def test_one_patient_called_at_a_time(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        first = await walked_in(client, await someone(client, "Asha"), doctor)
        second = await walked_in(client, await someone(client, "Bina"), doctor)
        await stepped(client, first["id"], "call")

        error = refusal(await step(client, second["id"], "call"))

        assert error["status"] == 409
        assert error["code"] == "QUEUE_INVALID_TRANSITION"
        assert error["message"].startswith("Token 1 has been called")

    async def test_one_patient_in_the_room_at_a_time(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        first = await walked_in(client, await someone(client, "Asha"), doctor)
        second = await walked_in(client, await someone(client, "Bina"), doctor)
        await stepped(client, first["id"], "start")

        # Calling the next one in while the doctor finishes is fine.
        await stepped(client, second["id"], "call")
        error = refusal(await step(client, second["id"], "start"))

        assert error["status"] == 409
        assert "Finish that consultation first" in error["message"]

    async def test_two_screens_calling_the_next_patient_at_once(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        first = await walked_in(client, await someone(client, "Asha"), doctor)
        second = await walked_in(client, await someone(client, "Bina"), doctor)

        answers = await asyncio.gather(
            step(client, first["id"], "call"), step(client, second["id"], "call")
        )

        assert sorted(answer.status_code for answer in answers) == [200, 409]

    async def test_a_double_click_on_finish_finishes_once(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        entry = await walked_in(client, await register(client), doctor)
        await stepped(client, entry["id"], "start")

        answers = await asyncio.gather(
            step(client, entry["id"], "complete"), step(client, entry["id"], "complete")
        )

        assert sorted(answer.status_code for answer in answers) == [200, 409]

    async def test_not_here_when_called_and_back_later(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        first = await walked_in(client, await someone(client, "Asha"), doctor)
        second = await walked_in(client, await someone(client, "Bina"), doctor)
        third = await walked_in(client, await someone(client, "Chitra"), doctor)
        await stepped(client, first["id"], "call")

        skipped = await stepped(client, first["id"], "skip")
        assert skipped["status"] == "skipped"
        lane = lane_of(await the_queue(client), doctor)
        assert [entry["id"] for entry in lane["skipped"]] == [first["id"]]
        assert lane["called"] is None
        # The next one can be called now.
        await stepped(client, second["id"], "call")
        await stepped(client, second["id"], "start")

        # Recalled, they go back to their own number, ahead of later arrivals.
        recalled = await stepped(client, first["id"], "recall")
        assert recalled["status"] == "waiting"
        lane = lane_of(await the_queue(client), doctor)
        assert [entry["id"] for entry in lane["waiting"]] == [first["id"], third["id"]]

    async def test_a_skipped_patient_has_to_be_recalled_before_being_called(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        entry = await walked_in(client, await register(client), doctor)
        await stepped(client, entry["id"], "call")
        await stepped(client, entry["id"], "skip")

        error = refusal(await step(client, entry["id"], "call"))

        assert error["message"] == "They missed their call. Recall them first."

    async def test_leaving_without_being_seen(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await booked_today(session, client, await register(client), doctor)
        entry = await checked_in(client, made)

        gone = await stepped(client, entry["id"], "no-show")

        assert gone["status"] == "no_show"
        booked = await appointment(client, made)
        assert booked["status"] == "no_show"
        assert booked["history"][-1]["event"] == "left"
        assert booked["history"][-1]["detail"] == "Left the queue, token 1"
        # Nothing further can happen to a place that has gone.
        assert refusal(await step(client, entry["id"], "call"))["status"] == 409

    async def test_nobody_leaves_from_the_room(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        entry = await walked_in(client, await register(client), doctor)
        await stepped(client, entry["id"], "start")

        error = refusal(await step(client, entry["id"], "no-show"))

        assert error["message"] == "They are with the doctor now."


class TestTheOrderOfTheLine:
    async def test_urgent_goes_first_and_the_waits_add_up(self, client: AsyncClient) -> None:
        await sign_up(client)
        # Thirty-minute appointments, which is the guess before anybody has
        # been seen today.
        doctor = await doctor_with_hours(client)
        asha = await walked_in(client, await someone(client, "Asha"), doctor)
        bina = await walked_in(client, await someone(client, "Bina"), doctor)
        chitra = await walked_in(client, await someone(client, "Chitra"), doctor)

        marked = await client.patch(f"{API}/queue/{chitra['id']}", json={"priority": "urgent"})
        assert marked.status_code == 200, marked.text

        lane = lane_of(await the_queue(client), doctor)
        assert [entry["id"] for entry in lane["waiting"]] == [
            chitra["id"],
            asha["id"],
            bina["id"],
        ]
        assert [entry["position"] for entry in lane["waiting"]] == [1, 2, 3]
        assert [entry["expected_wait_minutes"] for entry in lane["waiting"]] == [0, 30, 60]
        assert lane["average_minutes"] == 30

        # Somebody in the room pushes everybody's guess back.
        await stepped(client, chitra["id"], "start")
        lane = lane_of(await the_queue(client), doctor)
        assert [entry["expected_wait_minutes"] for entry in lane["waiting"]] == [30, 60]

    async def test_priority_cannot_be_changed_once_in_the_room(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        entry = await walked_in(client, await register(client), doctor)
        await stepped(client, entry["id"], "start")

        response = await client.patch(f"{API}/queue/{entry['id']}", json={"priority": "urgent"})

        assert refusal(response)["status"] == 409

    async def test_the_desk_sees_who_is_still_to_arrive(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        asha = await someone(client, "Asha")
        bina = await someone(client, "Bina")
        early = await booked_today(session, client, asha, doctor, at="00:30")
        await booked_today(session, client, bina, doctor, at="23:30")

        lane = lane_of(await the_queue(client), doctor)
        assert [arrival["patient"]["id"] for arrival in lane["expected"]] == [
            asha["id"],
            bina["id"],
        ]
        # Half past midnight has always gone by the time anyone runs this.
        assert lane["expected"][0]["is_late"] is True

        await checked_in(client, early)
        lane = lane_of(await the_queue(client), doctor)
        assert [arrival["patient"]["id"] for arrival in lane["expected"]] == [bina["id"]]


class TestUndoingACheckIn:
    async def test_a_mistaken_check_in_can_be_taken_back(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await booked_today(
            session, client, await register(client), doctor, status="confirmed"
        )
        entry = await checked_in(client, made)

        response = await client.delete(f"{API}/queue/{entry['id']}")

        assert response.status_code == 200, response.text
        restored = response.json()["data"]
        assert restored["status"] == "confirmed"
        assert restored["queue_token"] is None
        assert restored["history"][-1]["event"] == "check_in_undone"
        assert lane_of(await the_queue(client), doctor)["waiting"] == []
        assert (await client.get(f"{API}/queue/{entry['id']}")).status_code == 404
        # And they can be checked in properly afterwards.
        assert (await checked_in(client, made))["status"] == "waiting"

    async def test_a_walk_in_taken_back_answers_with_nothing(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        entry = await walked_in(client, await register(client), doctor)

        response = await client.delete(f"{API}/queue/{entry['id']}")

        assert response.status_code == 200, response.text
        assert response.json()["data"] is None

    async def test_not_once_they_have_been_called(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        entry = await walked_in(client, await register(client), doctor)
        await stepped(client, entry["id"], "call")
        await stepped(client, entry["id"], "skip")
        await stepped(client, entry["id"], "recall")

        error = refusal(await client.delete(f"{API}/queue/{entry['id']}"))

        assert error["status"] == 409
        assert "already been called" in error["message"]


class TestDaysGoneBy:
    async def test_a_place_left_open_yesterday_does_not_hold_up_today(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        yesterday = today() - dt.timedelta(days=1)
        stale = QueueEntry(
            organization_id=await clinic_id(client),
            patient_id=uuid.UUID(patient["id"]),
            doctor_id=uuid.UUID(doctor["id"]),
            token_date=yesterday,
            token_number=7,
            status="in_consultation",
            priority="normal",
            checked_in_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=1),
            started_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=1),
        )
        session.add(stale)
        await session.commit()

        entry = await walked_in(client, patient, doctor)
        assert entry["token"] == 1
        assert (await stepped(client, entry["id"], "start"))["status"] == "in_consultation"
        # Yesterday's is not in today's queue, and cannot be called into it.
        lane = lane_of(await the_queue(client), doctor)
        assert lane["now_seeing"]["id"] == entry["id"]
        # It can still be closed, which is what somebody tidying up would do.
        assert (await stepped(client, str(stale.id), "complete"))["status"] == "completed"


class TestWhoSeesWhat:
    async def test_another_clinic_cannot_see_or_touch_it(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        made = await booked_today(session, client, patient, doctor)
        entry = await checked_in(client, made)

        await client.post(f"{AUTH}/logout")
        await sign_up(client)
        own_doctor = await doctor_with_hours(client)

        for action in ("call", "start", "complete", "skip", "recall", "no-show"):
            assert (await step(client, entry["id"], action)).status_code == 404
        assert (await client.get(f"{API}/queue/{entry['id']}")).status_code == 404
        assert (await client.delete(f"{API}/queue/{entry['id']}")).status_code == 404
        assert (
            await client.patch(f"{API}/queue/{entry['id']}", json={"priority": "urgent"})
        ).status_code == 404
        assert (await check_in(client, made)).status_code == 404
        theirs_patient = refusal(await walk_in(client, patient, own_doctor))
        assert theirs_patient["status"] == 422 and "patient_id" in theirs_patient["fields"]
        theirs_doctor = refusal(await walk_in(client, await register(client), doctor))
        assert theirs_doctor["status"] == 422 and "doctor_id" in theirs_doctor["fields"]
        queue = await the_queue(client, doctor_id=doctor["id"])
        assert all(lane["doctor"]["id"] != doctor["id"] for lane in queue["lanes"])

    async def test_a_doctor_works_their_own_line_and_nobody_elses(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="doctor", outbox=outbox)
        member = await someone_else(client)
        mine = await doctor_with_hours(client, first_name="Ananya", user_id=member["id"])
        theirs = await doctor_with_hours(client, first_name="Vikram", last_name="Rao")
        own = await walked_in(client, await someone(client, "Asha"), mine)
        other = await walked_in(client, await someone(client, "Bina"), theirs)

        await client.post(f"{AUTH}/logout")
        await sign_in(client, address)

        queue = await the_queue(client, doctor_id=theirs["id"])
        assert [lane["doctor"]["id"] for lane in queue["lanes"]] == [mine["id"]]
        assert queue["only_doctor_id"] == mine["id"]

        await stepped(client, own["id"], "call")
        await stepped(client, own["id"], "start")
        await stepped(client, own["id"], "complete")
        assert (await step(client, other["id"], "call")).status_code == 404
        # Arrivals are the desk's job.
        assert (await walk_in(client, await someone(client, "Chitra"), mine)).status_code == 403

    async def test_a_doctor_with_no_profile_yet_sees_nothing(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="doctor", outbox=outbox)
        doctor = await doctor_with_hours(client)
        await walked_in(client, await register(client), doctor)

        await client.post(f"{AUTH}/logout")
        await sign_in(client, address)

        queue = await the_queue(client)
        assert queue["lanes"] == []
        assert queue["unlinked"] is True

    async def test_read_only_staff_can_watch_but_not_move_anyone(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="staff", outbox=outbox)
        doctor = await doctor_with_hours(client)
        entry = await walked_in(client, await someone(client, "Asha"), doctor)
        bina = await someone(client, "Bina")

        await client.post(f"{AUTH}/logout")
        await sign_in(client, address)

        assert len(lane_of(await the_queue(client), doctor)["waiting"]) == 1
        assert (await step(client, entry["id"], "call")).status_code == 403
        assert (await client.delete(f"{API}/queue/{entry['id']}")).status_code == 403
        assert (await walk_in(client, bina, doctor)).status_code == 403

    async def test_a_receptionist_runs_the_whole_thing(
        self, client: AsyncClient, outbox: Outbox, session: AsyncSession
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="receptionist", outbox=outbox)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        made = await booked_today(session, client, patient, doctor)

        await client.post(f"{AUTH}/logout")
        await sign_in(client, address)

        entry = await checked_in(client, made)
        await stepped(client, entry["id"], "call")
        await stepped(client, entry["id"], "start")
        assert (await stepped(client, entry["id"], "complete"))["status"] == "completed"
