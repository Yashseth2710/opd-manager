"""Appointments: booking into the rota, and everything that happens after.

Most of the weight is on the slot. A booking has to land on a time the
doctor's day actually offers, never on one somebody else already holds, and
never on one that has gone. The race between two desks booking the same
slot at once is tested against the database rather than assumed.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment
from tests.api.test_clinic import invite_and_accept, sign_in, sign_up, someone_else
from tests.api.test_doctors import add as add_doctor
from tests.api.test_doctors import set_schedule
from tests.api.test_patients import register
from tests.conftest import Outbox

API = "/api/v1"
AUTH = "/api/v1/auth"

# Where a clinic is unless it says otherwise.
KOLKATA = ZoneInfo("Asia/Kolkata")

# Nine to one with a half-hour break, in thirty-minute appointments:
# 9:00, 9:30, 10:00, 10:30, then 11:30, 12:00, 12:30.
MORNING = {
    "start_time": "09:00",
    "end_time": "13:00",
    "break_start": "11:00",
    "break_end": "11:30",
}


def clinic_day(days_ahead: int = 1) -> dt.date:
    return dt.datetime.now(KOLKATA).date() + dt.timedelta(days=days_ahead)


def next_on(day_of_week: int) -> dt.date:
    """The next date on this weekday, never today, at the clinic."""
    tomorrow = clinic_day(1)
    return tomorrow + dt.timedelta(days=(day_of_week - tomorrow.weekday()) % 7)


# Different enough from each other that duplicate detection has nothing to
# ask about: a shared surname and birthday reads as one person twice.
PEOPLE = {
    "Asha": ("Kulkarni", "9820011001", "1979-02-03"),
    "Bina": ("Menon", "9820011002", "1985-06-21"),
    "Chitra": ("Bhat", "9820011003", "1991-11-09"),
    "Deepa": ("Gill", "9820011004", "1968-08-30"),
    "Rahul": ("Joshi", "9820099887", "2001-01-15"),
}


async def someone(client: AsyncClient, first_name: str) -> dict[str, Any]:
    last_name, phone, born = PEOPLE[first_name]
    return await register(
        client, first_name=first_name, last_name=last_name, phone=phone, date_of_birth=born
    )


async def doctor_with_hours(
    client: AsyncClient, *, days: range = range(7), **details: Any
) -> dict[str, Any]:
    doctor = await add_doctor(client, slot_duration_minutes=30, **details)
    response = await set_schedule(
        client, doctor["id"], [{"day_of_week": day, **MORNING} for day in days]
    )
    assert response.status_code == 200, response.text
    return doctor


def booking(
    patient: dict[str, Any], doctor: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "patient_id": patient["id"],
        "doctor_id": doctor["id"],
        "date": clinic_day().isoformat(),
        "start_time": "09:00",
    }
    body.update(overrides)
    return body


async def book(
    client: AsyncClient, patient: dict[str, Any], doctor: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/appointments", json=booking(patient, doctor, **overrides)
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()["data"]
    return created


async def refused(
    client: AsyncClient, patient: dict[str, Any], doctor: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/appointments", json=booking(patient, doctor, **overrides)
    )
    assert response.status_code >= 400, response.text
    error: dict[str, Any] = response.json()["error"]
    error["status"] = response.status_code
    return error


async def free_times(client: AsyncClient, doctor_id: str, day: dt.date) -> dict[str, str]:
    response = await client.get(
        f"{API}/doctors/{doctor_id}/availability", params={"date": day.isoformat()}
    )
    assert response.status_code == 200, response.text
    return {slot["start_time"][:5]: slot["state"] for slot in response.json()["data"]["slots"]}


async def the_day(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/appointments", params=params)
    assert response.status_code == 200, response.text
    day: dict[str, Any] = response.json()["data"]
    return day


async def act(client: AsyncClient, appointment_id: str, action: str, **body: Any) -> Any:
    return await client.post(f"{API}/appointments/{appointment_id}/{action}", json=body)


async def clinic_id(client: AsyncClient) -> uuid.UUID:
    me = (await client.get(f"{AUTH}/me")).json()["data"]
    return uuid.UUID(me["organization"]["id"])


async def booked_earlier_today(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    patient: dict[str, Any],
    doctor: dict[str, Any],
) -> uuid.UUID:
    """An appointment that has already started, which the API will not book.

    Written straight to the table, the way the passage of time would leave it.
    """
    starts = dt.datetime.now(dt.UTC).replace(microsecond=0) - dt.timedelta(minutes=10)
    appointment = Appointment(
        organization_id=organization_id,
        patient_id=uuid.UUID(patient["id"]),
        doctor_id=uuid.UUID(doctor["id"]),
        scheduled_start=starts,
        scheduled_end=starts + dt.timedelta(minutes=30),
        appointment_type="consultation",
        source="desk",
        status="scheduled",
    )
    session.add(appointment)
    await session.commit()
    return appointment.id


class TestBooking:
    async def test_a_booking_lands_on_the_slot_and_says_so_in_clinic_time(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)

        made = await book(
            client, patient, doctor, start_time="10:30", reason="Cough for a week"
        )

        assert made["date"] == clinic_day().isoformat()
        assert made["start_time"] == "10:30:00"
        # The end comes from the slot, never from the request.
        assert made["end_time"] == "11:00:00"
        assert made["status"] == "scheduled"
        assert made["appointment_type"] == "consultation"
        assert made["reason"] == "Cough for a week"
        assert made["patient"]["patient_number"] == patient["patient_number"]
        assert made["doctor"]["display_name"] == doctor["display_name"]
        assert made["has_started"] is False
        assert made["conflict"] is None
        assert [line["event"] for line in made["history"]] == ["booked"]
        assert made["history"][0]["actor_name"]
        assert made["booked_by_name"] == made["history"][0]["actor_name"]

    async def test_the_instant_stored_is_the_clinics_wall_clock(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)

        made = await book(client, patient, doctor, start_time="09:00")

        starts = dt.datetime.fromisoformat(made["scheduled_start"])
        assert starts.astimezone(KOLKATA).time() == dt.time(9, 0)
        assert starts.astimezone(KOLKATA).date() == clinic_day()

    async def test_the_fee_follows_the_type_of_visit(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client, consultation_fee="600", follow_up_fee="250")
        patient = await register(client)

        first = await book(client, patient, doctor, start_time="09:00")
        again = await book(
            client, patient, doctor, start_time="09:30", appointment_type="follow_up"
        )

        assert first["fee"] == "600.00"
        assert again["fee"] == "250.00"

    async def test_a_booked_slot_stops_being_free_and_its_neighbours_do_not(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)

        await book(client, patient, doctor, start_time="09:30")

        states = await free_times(client, doctor["id"], clinic_day())
        assert states["09:30"] == "booked"
        assert states["09:00"] == "free"
        assert states["10:00"] == "free"
        # The break never offered a slot to begin with.
        assert "11:00" not in states

    async def test_back_to_back_appointments_do_not_collide(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        other = await someone(client, "Rahul")

        await book(client, patient, doctor, start_time="09:00")
        await book(client, other, doctor, start_time="09:30")


class TestTheSlotIsHeld:
    async def test_the_same_slot_cannot_be_booked_twice(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        first = await register(client)
        second = await someone(client, "Rahul")

        await book(client, first, doctor, start_time="10:00")
        error = await refused(client, second, doctor, start_time="10:00")

        assert error["status"] == 409
        assert error["code"] == "APPT_SLOT_UNAVAILABLE"

    async def test_two_desks_booking_the_same_slot_at_once_get_one_booking(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patients = [await someone(client, name) for name in ("Asha", "Bina", "Chitra", "Deepa")]

        answers = await asyncio.gather(
            *(
                client.post(
                    f"{API}/appointments", json=booking(patient, doctor, start_time="12:00")
                )
                for patient in patients
            )
        )

        codes = sorted(answer.status_code for answer in answers)
        assert codes == [201, 409, 409, 409]
        for answer in answers:
            if answer.status_code == 409:
                assert answer.json()["error"]["code"] == "APPT_SLOT_UNAVAILABLE"

        day = await the_day(client, date=clinic_day().isoformat())
        assert len([item for item in day["items"] if item["start_time"] == "12:00:00"]) == 1

    async def test_a_patient_cannot_be_in_two_rooms_at_once(self, client: AsyncClient) -> None:
        await sign_up(client)
        iyer = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        rao = await doctor_with_hours(client, first_name="Vikram", last_name="Rao")
        patient = await someone(client, "Asha")

        await book(client, patient, iyer, start_time="09:30")
        error = await refused(client, patient, rao, start_time="09:30")

        assert error["status"] == 409
        assert error["code"] == "APPT_PATIENT_BUSY"
        # Names who they are already with, which is the next thing asked.
        assert "Dr Ananya Iyer" in error["message"]
        assert "9:30 am" in error["message"]

    async def test_a_cancelled_slot_can_be_booked_again(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        first = await register(client)
        second = await someone(client, "Rahul")

        made = await book(client, first, doctor, start_time="10:00")
        assert (
            await act(client, made["id"], "cancel", reason="Feeling better")
        ).status_code == 200

        assert (await free_times(client, doctor["id"], clinic_day()))["10:00"] == "free"
        await book(client, second, doctor, start_time="10:00")


class TestRefusals:
    async def test_a_day_that_has_gone(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)

        error = await refused(client, patient, doctor, date=clinic_day(-1).isoformat())

        assert error["code"] == "APPT_PAST_DATE"
        assert "date" in error["fields"]

    async def test_a_day_the_doctor_does_not_sit(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client, days=range(6))
        patient = await register(client)

        error = await refused(client, patient, doctor, date=next_on(6).isoformat())

        assert error["code"] == "APPT_OUTSIDE_WORKING_HOURS"
        assert error["fields"]["date"].endswith("has no Sunday clinic.")

    async def test_a_time_that_is_not_one_of_the_slots(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)

        between = await refused(client, patient, doctor, start_time="09:10")
        after = await refused(client, patient, doctor, start_time="14:00")

        assert between["code"] == "APPT_OUTSIDE_WORKING_HOURS"
        assert "9:10 am is not one of" in between["fields"]["start_time"]
        assert after["code"] == "APPT_OUTSIDE_WORKING_HOURS"

    async def test_the_doctors_break(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)

        error = await refused(client, patient, doctor, start_time="11:00")

        assert error["code"] == "APPT_OUTSIDE_WORKING_HOURS"
        assert "break" in error["fields"]["start_time"]

    async def test_a_day_of_leave(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        day = clinic_day(2)
        await client.post(f"{API}/doctors/{doctor['id']}/leaves", json={"starts_on": str(day)})

        error = await refused(client, patient, doctor, date=day.isoformat())

        assert error["code"] == "APPT_DOCTOR_ON_LEAVE"
        assert "date" in error["fields"]

    async def test_a_few_hours_of_leave(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        day = clinic_day(2)
        await client.post(
            f"{API}/doctors/{doctor['id']}/leaves",
            json={"starts_on": str(day), "start_time": "09:00", "end_time": "10:00"},
        )

        error = await refused(client, patient, doctor, date=day.isoformat(), start_time="09:30")
        fine = await book(client, patient, doctor, date=day.isoformat(), start_time="10:00")

        assert error["code"] == "APPT_DOCTOR_ON_LEAVE"
        assert "start_time" in error["fields"]
        assert fine["status"] == "scheduled"

    async def test_more_than_a_year_ahead(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)

        error = await refused(client, patient, doctor, date=clinic_day(400).isoformat())

        assert error["code"] == "APPT_OUTSIDE_WORKING_HOURS"
        assert "a year ahead" in error["fields"]["date"]

    async def test_a_doctor_who_has_been_stood_down(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        await client.post(f"{API}/doctors/{doctor['id']}/deactivate")

        error = await refused(client, patient, doctor)

        assert error["status"] == 409
        assert error["code"] == "DOCTOR_INACTIVE"

    async def test_an_archived_patient(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        await client.post(f"{API}/patients/{patient['id']}/archive")

        error = await refused(client, patient, doctor)

        assert error["status"] == 409
        assert error["code"] == "PATIENT_ARCHIVED"

    async def test_nobody_that_exists(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        nobody = {"id": str(uuid.uuid4())}

        no_patient = await refused(client, nobody, doctor)
        no_doctor = await refused(client, patient, nobody)

        assert no_patient["status"] == 422
        assert "patient_id" in no_patient["fields"]
        assert no_doctor["status"] == 422
        assert "doctor_id" in no_doctor["fields"]

    async def test_what_the_form_sends_is_held_to_its_limits(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)

        too_long = await refused(client, patient, doctor, reason="x" * 201)
        odd_type = await refused(client, patient, doctor, appointment_type="surgery")
        no_time = await refused(client, patient, doctor, start_time="nine")

        assert too_long["status"] == 422 and "reason" in too_long["fields"]
        assert odd_type["status"] == 422 and "appointment_type" in odd_type["fields"]
        assert no_time["status"] == 422 and "start_time" in no_time["fields"]


class TestTheDay:
    async def test_the_day_lists_every_booking_in_time_order(self, client: AsyncClient) -> None:
        await sign_up(client)
        iyer = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        rao = await doctor_with_hours(client, first_name="Vikram", last_name="Rao")
        asha = await someone(client, "Asha")
        bina = await someone(client, "Bina")
        chitra = await someone(client, "Chitra")

        await book(client, asha, rao, start_time="10:00")
        await book(client, bina, iyer, start_time="09:00")
        cancelled = await book(client, chitra, iyer, start_time="12:00")
        await act(client, cancelled["id"], "cancel")
        # Another day, which this one should not show.
        await book(client, asha, iyer, date=clinic_day(2).isoformat())

        day = await the_day(client, date=clinic_day().isoformat())

        assert [item["start_time"] for item in day["items"]] == [
            "09:00:00",
            "10:00:00",
            "12:00:00",
        ]
        # A cancelled booking stays in the day, so the desk can see the slot
        # was given up rather than never taken.
        assert day["items"][2]["status"] == "cancelled"
        assert day["only_doctor_id"] is None
        assert day["unlinked"] is False

    async def test_one_doctors_day(self, client: AsyncClient) -> None:
        await sign_up(client)
        iyer = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        rao = await doctor_with_hours(client, first_name="Vikram", last_name="Rao")
        asha = await someone(client, "Asha")
        bina = await someone(client, "Bina")

        await book(client, asha, iyer, start_time="09:00")
        await book(client, bina, rao, start_time="09:00")

        day = await the_day(client, date=clinic_day().isoformat(), doctor_id=iyer["id"])

        assert [item["doctor"]["id"] for item in day["items"]] == [iyer["id"]]

    async def test_without_a_date_it_is_today_at_the_clinic(self, client: AsyncClient) -> None:
        await sign_up(client)

        day = await the_day(client)

        assert day["date"] == clinic_day(0).isoformat()
        assert day["is_today"] is True
        assert day["items"] == []

    async def test_leave_taken_after_booking_is_flagged_on_the_booking(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        patient = await register(client)
        made = await book(client, patient, doctor, date=clinic_day(3).isoformat())

        await client.post(
            f"{API}/doctors/{doctor['id']}/leaves", json={"starts_on": str(clinic_day(3))}
        )

        day = await the_day(client, date=clinic_day(3).isoformat())
        assert day["items"][0]["conflict"] == "Dr Ananya Iyer is on leave that day."
        # Nothing is moved or cancelled on the desk's behalf.
        assert day["items"][0]["status"] == "scheduled"
        detail = (await client.get(f"{API}/appointments/{made['id']}")).json()["data"]
        assert detail["conflict"] == "Dr Ananya Iyer is on leave that day."

    async def test_a_changed_rota_is_flagged_too(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        patient = await register(client)
        await book(client, patient, doctor, start_time="12:30")

        await set_schedule(
            client,
            doctor["id"],
            [
                {"day_of_week": day, "start_time": "09:00", "end_time": "12:00"}
                for day in range(7)
            ],
        )

        day = await the_day(client, date=clinic_day().isoformat())
        assert day["items"][0]["conflict"] == "This is outside Dr Ananya Iyer's hours now."

    async def test_a_doctor_stood_down_with_bookings_ahead(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        patient = await register(client)
        await book(client, patient, doctor)

        await client.post(f"{API}/doctors/{doctor['id']}/deactivate")

        day = await the_day(client, date=clinic_day().isoformat())
        assert "no longer seeing patients" in day["items"][0]["conflict"]


class TestWhatHappensNext:
    async def test_confirming(self, client: AsyncClient) -> None:
        await sign_up(client)
        made = await book(client, await register(client), await doctor_with_hours(client))

        confirmed = await act(client, made["id"], "confirm")
        twice = await act(client, made["id"], "confirm")

        assert confirmed.status_code == 200
        assert confirmed.json()["data"]["status"] == "confirmed"
        assert twice.status_code == 409
        assert twice.json()["error"]["message"] == "This appointment is already confirmed."

    async def test_cancelling_keeps_the_reason_and_who(self, client: AsyncClient) -> None:
        await sign_up(client)
        made = await book(client, await register(client), await doctor_with_hours(client))

        answer = await act(client, made["id"], "cancel", reason="Travelling that week")

        cancelled = answer.json()["data"]
        assert cancelled["status"] == "cancelled"
        assert cancelled["cancelled_reason"] == "Travelling that week"
        assert cancelled["cancelled_at"]
        assert [line["event"] for line in cancelled["history"]] == ["booked", "cancelled"]
        assert cancelled["history"][1]["detail"] == "Travelling that week"
        assert cancelled["history"][1]["from_status"] == "scheduled"

    async def test_nothing_can_be_done_to_a_cancelled_appointment(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        made = await book(client, await register(client), await doctor_with_hours(client))
        await act(client, made["id"], "cancel")

        again = await act(client, made["id"], "cancel")
        confirm = await act(client, made["id"], "confirm")
        move = await client.patch(
            f"{API}/appointments/{made['id']}", json={"start_time": "10:00"}
        )

        for answer in (again, confirm, move):
            assert answer.status_code == 409
            assert answer.json()["error"]["message"] == "This appointment was cancelled."

    async def test_a_no_show_cannot_be_marked_before_it_starts(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        made = await book(client, await register(client), await doctor_with_hours(client))

        early = await act(client, made["id"], "no-show")

        assert early.status_code == 409
        assert "not started yet" in early.json()["error"]["message"]

    async def test_a_no_show_once_it_has_started(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        started = await booked_earlier_today(
            session, organization_id=await clinic_id(client), patient=patient, doctor=doctor
        )

        detail = (await client.get(f"{API}/appointments/{started}")).json()["data"]
        assert detail["has_started"] is True
        marked = await act(client, str(started), "no-show")

        assert marked.status_code == 200
        assert marked.json()["data"]["status"] == "no_show"
        assert marked.json()["data"]["history"][-1]["event"] == "no_show"

    async def test_confirming_something_already_over_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        started = await booked_earlier_today(
            session, organization_id=await clinic_id(client), patient=patient, doctor=doctor
        )
        await session.execute(
            update(Appointment)
            .where(Appointment.id == started)
            .values(scheduled_end=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
        )
        await session.commit()

        answer = await act(client, str(started), "confirm")

        assert answer.status_code == 409
        assert answer.json()["error"]["message"] == "This appointment has already happened."


class TestMoving:
    async def test_moving_frees_the_old_slot_and_asks_again(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await book(client, await register(client), doctor, start_time="09:00")
        await act(client, made["id"], "confirm")

        answer = await client.patch(
            f"{API}/appointments/{made['id']}",
            json={"date": clinic_day(2).isoformat(), "start_time": "12:30"},
        )

        moved = answer.json()["data"]
        assert answer.status_code == 200
        assert moved["date"] == clinic_day(2).isoformat()
        assert moved["start_time"] == "12:30:00"
        # Agreeing to one day is not agreeing to another.
        assert moved["status"] == "scheduled"
        assert moved["history"][-1]["event"] == "rescheduled"
        assert moved["history"][-1]["from_status"] == "confirmed"
        assert moved["history"][-1]["detail"].startswith("Moved from ")
        assert moved["history"][-1]["detail"].endswith(", 9:00 am")

        assert (await free_times(client, doctor["id"], clinic_day()))["09:00"] == "free"
        assert (await free_times(client, doctor["id"], clinic_day(2)))["12:30"] == "booked"

    async def test_moving_to_a_neighbouring_slot_does_not_clash_with_itself(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await book(client, await register(client), doctor, start_time="09:00")

        answer = await client.patch(
            f"{API}/appointments/{made['id']}", json={"start_time": "09:30"}
        )

        assert answer.status_code == 200, answer.text

    async def test_moving_onto_a_taken_slot(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        first = await book(client, await register(client), doctor, start_time="09:00")
        other = await someone(client, "Rahul")
        await book(client, other, doctor, start_time="10:00")

        answer = await client.patch(
            f"{API}/appointments/{first['id']}", json={"start_time": "10:00"}
        )

        assert answer.status_code == 409
        assert answer.json()["error"]["code"] == "APPT_SLOT_UNAVAILABLE"

    async def test_moving_to_another_doctor_at_the_same_time(self, client: AsyncClient) -> None:
        await sign_up(client)
        iyer = await doctor_with_hours(client, first_name="Ananya", last_name="Iyer")
        rao = await doctor_with_hours(client, first_name="Vikram", last_name="Rao")
        made = await book(client, await register(client), iyer, start_time="09:00")

        answer = await client.patch(
            f"{API}/appointments/{made['id']}", json={"doctor_id": rao["id"]}
        )

        moved = answer.json()["data"]
        assert moved["doctor"]["id"] == rao["id"]
        assert moved["start_time"] == "09:00:00"
        assert moved["history"][-1]["detail"].endswith("with Dr Ananya Iyer")

    async def test_asking_for_the_same_time_again_changes_nothing(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        made = await book(client, await register(client), doctor, start_time="09:00")
        await act(client, made["id"], "confirm")

        answer = await client.patch(
            f"{API}/appointments/{made['id']}",
            json={"date": clinic_day().isoformat(), "start_time": "09:00"},
        )

        same = answer.json()["data"]
        assert same["status"] == "confirmed"
        assert [line["event"] for line in same["history"]] == ["booked", "confirmed"]

    async def test_correcting_the_details_is_its_own_line(self, client: AsyncClient) -> None:
        await sign_up(client)
        made = await book(
            client, await register(client), await doctor_with_hours(client), notes="Wheelchair"
        )

        answer = await client.patch(
            f"{API}/appointments/{made['id']}",
            json={"reason": "Knee pain", "notes": None, "appointment_type": "follow_up"},
        )

        edited = answer.json()["data"]
        assert edited["reason"] == "Knee pain"
        assert edited["notes"] is None
        assert edited["appointment_type"] == "follow_up"
        assert edited["status"] == "scheduled"
        assert edited["history"][-1]["event"] == "edited"
        assert edited["history"][-1]["detail"] == "Changed the type, reason and notes."


class TestWhoSeesWhat:
    async def test_another_clinic_cannot_see_or_touch_it(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        made = await book(client, patient, doctor)

        await client.post(f"{AUTH}/logout")
        await sign_up(client)
        own_doctor = await doctor_with_hours(client)
        own_patient = await register(client)

        read = await client.get(f"{API}/appointments/{made['id']}")
        cancel = await act(client, made["id"], "cancel")
        move = await client.patch(
            f"{API}/appointments/{made['id']}", json={"start_time": "10:00"}
        )
        theirs_patient = await refused(client, patient, own_doctor)
        theirs_doctor = await refused(client, own_patient, doctor)
        listing = await client.get(f"{API}/patients/{patient['id']}/appointments")

        for answer in (read, cancel, move, listing):
            assert answer.status_code == 404
        assert theirs_patient["status"] == 422 and "patient_id" in theirs_patient["fields"]
        assert theirs_doctor["status"] == 422 and "doctor_id" in theirs_doctor["fields"]
        assert (await the_day(client, date=clinic_day().isoformat()))["items"] == []

    async def test_a_doctor_sees_only_their_own_list(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="doctor", outbox=outbox)
        member = await someone_else(client)
        mine = await doctor_with_hours(client, first_name="Ananya", user_id=member["id"])
        theirs = await doctor_with_hours(client, first_name="Vikram", last_name="Rao")
        asha = await someone(client, "Asha")
        bina = await someone(client, "Bina")
        own = await book(client, asha, mine, start_time="09:00")
        other = await book(client, bina, theirs, start_time="09:00")

        await client.post(f"{AUTH}/logout")
        await sign_in(client, address)

        day = await the_day(client, date=clinic_day().isoformat())
        assert [item["id"] for item in day["items"]] == [own["id"]]
        assert day["only_doctor_id"] == mine["id"]
        # Asking for somebody else's list gives their own all the same.
        asked = await the_day(client, date=clinic_day().isoformat(), doctor_id=theirs["id"])
        assert [item["id"] for item in asked["items"]] == [own["id"]]

        assert (await client.get(f"{API}/appointments/{other['id']}")).status_code == 404
        assert (await act(client, other["id"], "cancel")).status_code == 404
        into_theirs = await refused(client, asha, theirs, start_time="10:00")
        assert into_theirs["fields"]["doctor_id"] == "You can only book into your own list."
        assert (await book(client, bina, mine, start_time="10:00"))["status"] == "scheduled"

        history = (await client.get(f"{API}/patients/{bina['id']}/appointments")).json()["data"]
        assert [item["doctor"]["id"] for item in history["upcoming"]] == [mine["id"]]

    async def test_a_doctor_with_no_profile_yet_sees_nothing(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="doctor", outbox=outbox)
        doctor = await doctor_with_hours(client)
        await book(client, await register(client), doctor)

        await client.post(f"{AUTH}/logout")
        await sign_in(client, address)

        day = await the_day(client, date=clinic_day().isoformat())
        assert day["items"] == []
        assert day["unlinked"] is True

    async def test_read_only_staff_can_look_but_not_book(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = await invite_and_accept(client, role="staff", outbox=outbox)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        made = await book(client, patient, doctor)

        await client.post(f"{AUTH}/logout")
        await sign_in(client, address)

        assert len((await the_day(client, date=clinic_day().isoformat()))["items"]) == 1
        booking_refused = await client.post(
            f"{API}/appointments", json=booking(patient, doctor, start_time="10:00")
        )
        assert booking_refused.status_code == 403
        assert (await act(client, made["id"], "cancel")).status_code == 403
        assert (await act(client, made["id"], "confirm")).status_code == 403


class TestAPatientsAppointments:
    async def test_coming_up_and_what_has_been(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        doctor = await doctor_with_hours(client)
        patient = await register(client)
        later = await book(client, patient, doctor, date=clinic_day(5).isoformat())
        sooner = await book(client, patient, doctor, date=clinic_day(1).isoformat())
        dropped = await book(client, patient, doctor, date=clinic_day(3).isoformat())
        await act(client, dropped["id"], "cancel")
        earlier = await booked_earlier_today(
            session, organization_id=await clinic_id(client), patient=patient, doctor=doctor
        )
        await session.execute(
            update(Appointment)
            .where(Appointment.id == earlier)
            .values(scheduled_end=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
        )
        await session.commit()

        answer = await client.get(f"{API}/patients/{patient['id']}/appointments")
        found = answer.json()["data"]

        # Soonest first for what is ahead, latest first for what is behind.
        assert [item["id"] for item in found["upcoming"]] == [sooner["id"], later["id"]]
        assert [item["id"] for item in found["history"]] == [dropped["id"], str(earlier)]

    async def test_nobody_by_that_id(self, client: AsyncClient) -> None:
        await sign_up(client)

        answer = await client.get(f"{API}/patients/{uuid.uuid4()}/appointments")

        assert answer.status_code == 404
        assert answer.json()["error"]["code"] == "PATIENT_NOT_FOUND"
