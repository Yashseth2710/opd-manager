"""Doctors: profiles, the week they sit, leave, and who is free when.

The weight here is on two things. A fee left blank has to keep following the
clinic's figure rather than freezing a copy of it, because a clinic that
raises its consultation fee expects that to mean something. And the rota has
to refuse a week that cannot be sat — two blocks over the same hour is a
doctor in two rooms, and the slot list would hand the same minute out twice.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from httpx import AsyncClient

from tests.api.test_clinic import invite_and_accept, sign_in, sign_up
from tests.conftest import Outbox, unique_email

API = "/api/v1"
AUTH = "/api/v1/auth"

MONDAY = 0
TUESDAY = 1
SUNDAY = 6


def details(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "first_name": "Ananya",
        "last_name": "Iyer",
        "speciality": "Paediatrics",
        "qualifications": "MBBS, MD",
        "phone": "9820033445",
    }
    body.update(overrides)
    return body


async def add(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/doctors", json=details(**overrides))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()["data"]
    return created


async def listing(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/doctors", params=params)
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()["data"]
    return page


async def set_schedule(
    client: AsyncClient, doctor_id: str, blocks: list[dict[str, Any]]
) -> Any:
    return await client.put(f"{API}/doctors/{doctor_id}/schedule", json={"blocks": blocks})


def block(day: int = MONDAY, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "day_of_week": day,
        "start_time": "09:00",
        "end_time": "12:00",
    }
    body.update(overrides)
    return body


def next_weekday(day_of_week: int) -> dt.date:
    """The next date that falls on this weekday, today included.

    Availability is asked about a real date, so a test that wants a Monday
    has to find one rather than assume the suite runs on one.
    """
    today = dt.date.today()
    return today + dt.timedelta(days=(day_of_week - today.weekday()) % 7)


class TestAdding:
    async def test_a_doctor_is_named_the_way_a_patient_would_say_it(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await add(client)

        assert doctor["display_name"] == "Dr Ananya Iyer"
        assert doctor["full_name"] == "Ananya Iyer"
        assert doctor["status"] == "active"

    async def test_one_name_is_a_whole_name(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client, first_name="Sadhana", last_name=None)

        assert doctor["full_name"] == "Sadhana"
        assert doctor["display_name"] == "Dr Sadhana"

    async def test_a_title_other_than_doctor_is_allowed(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client, title="Prof")

        assert doctor["display_name"] == "Prof Ananya Iyer"

    async def test_a_new_doctor_has_no_hours_yet(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)

        assert doctor["working_days"] == 0
        assert doctor["schedule"] == []

    async def test_two_doctors_cannot_share_a_registration_number(
        self, client: AsyncClient
    ) -> None:
        """A council number identifies one clinician. Two profiles carrying
        the same one means a prescription can be printed against either."""
        await sign_up(client)
        await add(client, registration_number="MH-2019-44821")
        clash = await client.post(
            f"{API}/doctors",
            json=details(first_name="Rohit", registration_number="mh-2019-44821"),
        )

        assert clash.status_code == 409
        assert clash.json()["error"]["code"] == "REGISTRATION_NUMBER_TAKEN"

    async def test_the_same_number_at_another_clinic_is_fine(self, client: AsyncClient) -> None:
        await sign_up(client)
        await add(client, registration_number="MH-2019-44821")
        await client.post(f"{AUTH}/logout")

        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("owner"))
        theirs = await add(client, registration_number="MH-2019-44821")

        assert theirs["registration_number"] == "MH-2019-44821"

    async def test_languages_are_tidied_rather_than_stored_as_typed(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await add(client, languages=["Hindi", " hindi ", "Marathi", "  "])

        assert doctor["languages"] == ["Hindi", "Marathi"]


class TestFees:
    async def test_a_blank_fee_follows_the_clinic(self, client: AsyncClient) -> None:
        await sign_up(client)
        await client.patch(f"{API}/clinic/settings", json={"consultation_fee": "500.00"})
        doctor = await add(client)

        assert doctor["consultation_fee"] == "500.00"
        assert doctor["fee_from_clinic"] is True
        assert doctor["own_consultation_fee"] is None

    async def test_raising_the_clinic_fee_reaches_a_doctor_who_never_set_one(
        self, client: AsyncClient
    ) -> None:
        """The reason the column is nullable rather than copied on write."""
        await sign_up(client)
        doctor = await add(client)
        await client.patch(f"{API}/clinic/settings", json={"consultation_fee": "750.00"})

        again = (await client.get(f"{API}/doctors/{doctor['id']}")).json()["data"]
        assert again["consultation_fee"] == "750.00"

    async def test_a_doctor_who_charges_their_own_keeps_it(self, client: AsyncClient) -> None:
        await sign_up(client)
        await client.patch(f"{API}/clinic/settings", json={"consultation_fee": "500.00"})
        doctor = await add(client, consultation_fee="1200.00")
        await client.patch(f"{API}/clinic/settings", json={"consultation_fee": "750.00"})

        again = (await client.get(f"{API}/doctors/{doctor['id']}")).json()["data"]
        assert again["consultation_fee"] == "1200.00"
        assert again["fee_from_clinic"] is False

    async def test_free_is_a_fee_rather_than_a_blank(self, client: AsyncClient) -> None:
        """Clinics see staff families for nothing. Zero has to survive."""
        await sign_up(client)
        await client.patch(f"{API}/clinic/settings", json={"consultation_fee": "500.00"})
        doctor = await add(client, consultation_fee="0.00")

        assert doctor["consultation_fee"] == "0.00"
        assert doctor["fee_from_clinic"] is False

    async def test_clearing_a_fee_goes_back_to_following_the_clinic(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        await client.patch(f"{API}/clinic/settings", json={"consultation_fee": "500.00"})
        doctor = await add(client, consultation_fee="1200.00")

        await client.patch(f"{API}/doctors/{doctor['id']}", json={"consultation_fee": None})
        again = (await client.get(f"{API}/doctors/{doctor['id']}")).json()["data"]

        assert again["consultation_fee"] == "500.00"
        assert again["fee_from_clinic"] is True

    async def test_slot_length_follows_the_clinic_the_same_way(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        await client.patch(f"{API}/clinic/settings", json={"consultation_duration_minutes": 20})
        doctor = await add(client)

        assert doctor["slot_duration_minutes"] == 20
        assert doctor["own_slot_duration_minutes"] is None


class TestFinding:
    async def test_the_list_holds_only_the_active_by_default(self, client: AsyncClient) -> None:
        await sign_up(client)
        staying = await add(client)
        leaving = await add(client, first_name="Rohit", last_name="Menon")
        await client.post(f"{API}/doctors/{leaving['id']}/deactivate")

        page = await listing(client)
        assert [item["id"] for item in page["items"]] == [staying["id"]]

        everyone = await listing(client, status="all")
        assert everyone["total"] == 2

    async def test_a_misspelt_name_still_finds_them(self, client: AsyncClient) -> None:
        await sign_up(client)
        await add(client, first_name="Ananya", last_name="Deshmukh")

        page = await listing(client, q="deshmuk")
        assert page["total"] == 1

    async def test_searching_by_speciality(self, client: AsyncClient) -> None:
        await sign_up(client)
        await add(client, speciality="Cardiology")
        await add(client, first_name="Rohit", speciality="Paediatrics")

        page = await listing(client, q="cardio")
        assert [item["speciality"] for item in page["items"]] == ["Cardiology"]

    async def test_filtering_by_speciality_is_exact_where_search_is_not(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        await add(client, speciality="Cardiology")
        await add(client, first_name="Rohit", speciality="Paediatrics")

        page = await listing(client, speciality="paediatrics")
        assert page["total"] == 1

    async def test_the_speciality_list_is_what_this_clinic_offers(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        await add(client, speciality="Cardiology")
        await add(client, first_name="Rohit", speciality="Paediatrics")
        await add(client, first_name="Sneha", speciality="Cardiology")

        response = await client.get(f"{API}/doctors/specialities")
        assert response.json()["data"] == ["Cardiology", "Paediatrics"]

    async def test_a_speciality_nobody_practises_any_more_is_not_offered(
        self, client: AsyncClient
    ) -> None:
        """The list is a filter over the doctors being shown. Offering one
        that can only come back empty is a dead end on the screen."""
        await sign_up(client)
        await add(client, speciality="Cardiology")
        only = await add(client, first_name="Vikram", speciality="Orthopaedics")
        await client.post(f"{API}/doctors/{only['id']}/deactivate")

        practising = await client.get(f"{API}/doctors/specialities")
        assert practising.json()["data"] == ["Cardiology"]

        everyone = await client.get(f"{API}/doctors/specialities", params={"status": "all"})
        assert everyone.json()["data"] == ["Cardiology", "Orthopaedics"]

    async def test_a_bare_wildcard_does_not_match_everybody(self, client: AsyncClient) -> None:
        """LIKE reads % as "anything", so an unescaped one turns a search box
        into a way of listing the clinic."""
        await sign_up(client)
        await add(client)
        await add(client, first_name="Rohit")

        page = await listing(client, q="%")
        assert page["total"] == 0

    async def test_paging_never_repeats_a_doctor(self, client: AsyncClient) -> None:
        await sign_up(client)
        for index in range(7):
            await add(client, first_name=f"Doctor{index}", last_name="Same")

        first = await listing(client, per_page=3, page=1)
        second = await listing(client, per_page=3, page=2)
        third = await listing(client, per_page=3, page=3)

        seen = [item["id"] for page in (first, second, third) for item in page["items"]]
        assert len(seen) == len(set(seen)) == 7
        assert first["pages"] == 3

    async def test_working_days_are_counted_on_the_list(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)
        await set_schedule(
            client,
            doctor["id"],
            [
                block(MONDAY),
                block(MONDAY, start_time="17:00", end_time="20:00"),
                block(TUESDAY),
            ],
        )

        page = await listing(client)
        # Two blocks on Monday is one working day, not two.
        assert page["items"][0]["working_days"] == 2


class TestLinkingAnAccount:
    async def test_a_doctor_can_be_tied_to_the_account_they_sign_in_with(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        owner = await sign_up(client)
        joiner = await invite_and_accept(client, role="doctor", outbox=outbox)
        member = next(
            person
            for person in (await client.get(f"{API}/staff")).json()["data"]
            if person["email"] == joiner
        )

        doctor = await add(client, user_id=member["id"])
        assert doctor["has_account"] is True
        assert doctor["account_name"] == "Joiner Person"
        assert owner["user"]["email"]

    async def test_one_account_cannot_be_two_doctors(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        joiner = await invite_and_accept(client, role="doctor", outbox=outbox)
        member = next(
            person
            for person in (await client.get(f"{API}/staff")).json()["data"]
            if person["email"] == joiner
        )
        await add(client, user_id=member["id"])

        clash = await client.post(
            f"{API}/doctors", json=details(first_name="Rohit", user_id=member["id"])
        )
        assert clash.status_code == 409
        assert clash.json()["error"]["code"] == "ACCOUNT_ALREADY_LINKED"

    async def test_another_clinics_account_reads_as_nobody(self, client: AsyncClient) -> None:
        """Never as confirmation that the account exists somewhere else."""
        await sign_up(client)
        theirs = (await client.get(f"{AUTH}/me")).json()["data"]["user"]["id"]
        await client.post(f"{AUTH}/logout")

        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("owner"))
        refused = await client.post(f"{API}/doctors", json=details(user_id=theirs))

        assert refused.status_code == 422
        assert "user_id" in refused.json()["error"]["fields"]


class TestTheWeek:
    async def test_a_week_is_written_in_one_go(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)

        response = await set_schedule(
            client,
            doctor["id"],
            [
                block(MONDAY, start_time="09:00", end_time="13:00"),
                block(MONDAY, start_time="17:00", end_time="20:00"),
            ],
        )
        assert response.status_code == 200, response.text
        blocks = response.json()["data"]
        assert [item["start_time"] for item in blocks] == ["09:00:00", "17:00:00"]

    async def test_sending_it_again_replaces_rather_than_adds(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await add(client)
        await set_schedule(client, doctor["id"], [block(MONDAY), block(TUESDAY)])

        await set_schedule(client, doctor["id"], [block(TUESDAY)])
        again = (await client.get(f"{API}/doctors/{doctor['id']}/schedule")).json()["data"]

        assert [item["day_of_week"] for item in again] == [TUESDAY]

    async def test_an_empty_week_clears_it(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)
        await set_schedule(client, doctor["id"], [block(MONDAY)])

        await set_schedule(client, doctor["id"], [])
        again = (await client.get(f"{API}/doctors/{doctor['id']}/schedule")).json()["data"]

        assert again == []

    async def test_two_blocks_over_the_same_hour_are_refused(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)

        refused = await set_schedule(
            client,
            doctor["id"],
            [
                block(MONDAY, start_time="09:00", end_time="13:00"),
                block(MONDAY, start_time="12:00", end_time="15:00"),
            ],
        )
        assert refused.status_code == 422
        fields = refused.json()["error"]["fields"]
        assert any("Monday" in message for message in fields.values())

    async def test_blocks_that_touch_are_not_an_overlap(self, client: AsyncClient) -> None:
        """A morning ending at one and an afternoon starting at one is a
        normal week, not a double booking."""
        await sign_up(client)
        doctor = await add(client)

        response = await set_schedule(
            client,
            doctor["id"],
            [
                block(MONDAY, start_time="09:00", end_time="13:00"),
                block(MONDAY, start_time="13:00", end_time="17:00"),
            ],
        )
        assert response.status_code == 200, response.text

    async def test_the_same_hours_on_two_days_are_fine(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)

        response = await set_schedule(client, doctor["id"], [block(MONDAY), block(TUESDAY)])
        assert response.status_code == 200, response.text

    async def test_a_block_that_ends_before_it_starts_is_refused(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await add(client)

        refused = await set_schedule(
            client, doctor["id"], [block(MONDAY, start_time="17:00", end_time="09:00")]
        )
        assert refused.status_code == 422
        assert "blocks.0.end_time" in refused.json()["error"]["fields"]

    async def test_a_break_has_to_sit_inside_the_hours_it_breaks(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await add(client)

        refused = await set_schedule(
            client,
            doctor["id"],
            [block(MONDAY, break_start="14:00", break_end="15:00")],
        )
        assert refused.status_code == 422
        assert "blocks.0.break_start" in refused.json()["error"]["fields"]

    async def test_a_block_shorter_than_one_appointment_is_refused(
        self, client: AsyncClient
    ) -> None:
        """Otherwise it saves happily and produces a day with no slots in it."""
        await sign_up(client)
        doctor = await add(client)

        refused = await set_schedule(
            client,
            doctor["id"],
            [
                block(
                    MONDAY,
                    start_time="09:00",
                    end_time="09:10",
                    slot_duration_minutes=30,
                )
            ],
        )
        assert refused.status_code == 422
        assert "blocks.0.end_time" in refused.json()["error"]["fields"]

    async def test_a_day_outside_the_week_is_refused(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)

        refused = await set_schedule(client, doctor["id"], [block(9)])
        assert refused.status_code == 422

    async def test_a_refused_week_leaves_the_old_one_alone(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)
        await set_schedule(client, doctor["id"], [block(MONDAY)])

        await set_schedule(
            client,
            doctor["id"],
            [block(TUESDAY), block(TUESDAY, start_time="11:00", end_time="14:00")],
        )
        kept = (await client.get(f"{API}/doctors/{doctor['id']}/schedule")).json()["data"]

        assert [item["day_of_week"] for item in kept] == [MONDAY]


class TestLeave:
    async def test_one_day_off_needs_only_a_date(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)

        response = await client.post(
            f"{API}/doctors/{doctor['id']}/leaves",
            json={"starts_on": "2026-10-02", "reason": "Gandhi Jayanti"},
        )
        assert response.status_code == 201, response.text
        leave = response.json()["data"]
        assert leave["ends_on"] == "2026-10-02"
        assert leave["start_time"] is None

    async def test_leave_cannot_end_before_it_starts(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)

        refused = await client.post(
            f"{API}/doctors/{doctor['id']}/leaves",
            json={"starts_on": "2026-10-10", "ends_on": "2026-10-02"},
        )
        assert refused.status_code == 422
        assert "ends_on" in refused.json()["error"]["fields"]

    async def test_half_a_time_range_is_refused(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)

        refused = await client.post(
            f"{API}/doctors/{doctor['id']}/leaves",
            json={"starts_on": "2026-10-02", "start_time": "14:00"},
        )
        assert refused.status_code == 422

    async def test_leave_can_be_cancelled(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)
        leave = (
            await client.post(
                f"{API}/doctors/{doctor['id']}/leaves", json={"starts_on": "2026-10-02"}
            )
        ).json()["data"]

        removed = await client.delete(f"{API}/doctors/{doctor['id']}/leaves/{leave['id']}")
        assert removed.status_code == 200
        assert removed.json()["data"]["removed"] is True

    async def test_leave_that_finished_is_not_carried_on_the_profile(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await add(client)
        await client.post(
            f"{API}/doctors/{doctor['id']}/leaves", json={"starts_on": "2020-01-06"}
        )
        await client.post(
            f"{API}/doctors/{doctor['id']}/leaves",
            json={"starts_on": (dt.date.today() + dt.timedelta(days=30)).isoformat()},
        )

        profile = (await client.get(f"{API}/doctors/{doctor['id']}")).json()["data"]
        assert len(profile["leaves"]) == 1


class TestAvailability:
    async def test_a_morning_clinic_becomes_slots(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client, slot_duration_minutes=30)
        await set_schedule(
            client, doctor["id"], [block(MONDAY, start_time="09:00", end_time="11:00")]
        )

        day = next_weekday(MONDAY)
        found = (
            await client.get(
                f"{API}/doctors/{doctor['id']}/availability", params={"date": day.isoformat()}
            )
        ).json()["data"]

        assert found["working"] is True
        assert [slot["start_time"] for slot in found["slots"]] == [
            "09:00:00",
            "09:30:00",
            "10:00:00",
            "10:30:00",
        ]

    async def test_a_break_takes_its_slots_out(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client, slot_duration_minutes=30)
        await set_schedule(
            client,
            doctor["id"],
            [
                block(
                    MONDAY,
                    start_time="09:00",
                    end_time="11:00",
                    break_start="09:30",
                    break_end="10:00",
                )
            ],
        )

        day = next_weekday(MONDAY)
        found = (
            await client.get(
                f"{API}/doctors/{doctor['id']}/availability", params={"date": day.isoformat()}
            )
        ).json()["data"]

        assert [slot["start_time"] for slot in found["slots"]] == [
            "09:00:00",
            "10:00:00",
            "10:30:00",
        ]

    async def test_a_trailing_gap_too_short_for_an_appointment_is_not_offered(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await add(client, slot_duration_minutes=30)
        await set_schedule(
            client, doctor["id"], [block(MONDAY, start_time="09:00", end_time="10:20")]
        )

        day = next_weekday(MONDAY)
        found = (
            await client.get(
                f"{API}/doctors/{doctor['id']}/availability", params={"date": day.isoformat()}
            )
        ).json()["data"]

        assert [slot["end_time"] for slot in found["slots"]] == ["09:30:00", "10:00:00"]

    async def test_a_day_with_no_clinic_says_so(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)
        await set_schedule(client, doctor["id"], [block(MONDAY)])

        day = next_weekday(SUNDAY)
        found = (
            await client.get(
                f"{API}/doctors/{doctor['id']}/availability", params={"date": day.isoformat()}
            )
        ).json()["data"]

        assert found["working"] is False
        assert found["reason"] == "No Sunday clinic."
        assert found["slots"] == []

    async def test_a_whole_day_of_leave_closes_the_day(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)
        await set_schedule(client, doctor["id"], [block(MONDAY)])
        day = next_weekday(MONDAY)
        await client.post(
            f"{API}/doctors/{doctor['id']}/leaves",
            json={"starts_on": day.isoformat(), "reason": "Conference"},
        )

        found = (
            await client.get(
                f"{API}/doctors/{doctor['id']}/availability", params={"date": day.isoformat()}
            )
        ).json()["data"]

        assert found["working"] is False
        assert "Conference" in found["reason"]

    async def test_a_couple_of_hours_away_takes_only_those_slots(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await add(client, slot_duration_minutes=30)
        await set_schedule(
            client, doctor["id"], [block(MONDAY, start_time="09:00", end_time="12:00")]
        )
        day = next_weekday(MONDAY)
        await client.post(
            f"{API}/doctors/{doctor['id']}/leaves",
            json={
                "starts_on": day.isoformat(),
                "start_time": "10:00",
                "end_time": "11:00",
            },
        )

        found = (
            await client.get(
                f"{API}/doctors/{doctor['id']}/availability", params={"date": day.isoformat()}
            )
        ).json()["data"]

        assert [slot["start_time"] for slot in found["slots"]] == [
            "09:00:00",
            "09:30:00",
            "11:00:00",
            "11:30:00",
        ]

    async def test_a_block_can_run_at_its_own_pace(self, client: AsyncClient) -> None:
        """An evening clinic at ten minutes a head while the morning runs at
        thirty is how a lot of OPDs work."""
        await sign_up(client)
        doctor = await add(client, slot_duration_minutes=30)
        await set_schedule(
            client,
            doctor["id"],
            [
                block(MONDAY, start_time="09:00", end_time="10:00"),
                block(
                    MONDAY,
                    start_time="17:00",
                    end_time="17:30",
                    slot_duration_minutes=10,
                ),
            ],
        )

        day = next_weekday(MONDAY)
        found = (
            await client.get(
                f"{API}/doctors/{doctor['id']}/availability", params={"date": day.isoformat()}
            )
        ).json()["data"]

        assert [slot["start_time"] for slot in found["slots"]] == [
            "09:00:00",
            "09:30:00",
            "17:00:00",
            "17:10:00",
            "17:20:00",
        ]

    async def test_asking_without_a_date_means_today(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)

        found = (await client.get(f"{API}/doctors/{doctor['id']}/availability")).json()["data"]

        assert found["day_of_week"] in range(7)
        assert found["date"]

    async def test_a_doctor_who_has_been_stood_down_is_not_available(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        doctor = await add(client)
        await set_schedule(client, doctor["id"], [block(MONDAY)])
        await client.post(f"{API}/doctors/{doctor['id']}/deactivate")

        day = next_weekday(MONDAY)
        found = (
            await client.get(
                f"{API}/doctors/{doctor['id']}/availability", params={"date": day.isoformat()}
            )
        ).json()["data"]

        assert found["working"] is False
        assert found["slots"] == []


class TestStandingDown:
    async def test_deactivating_keeps_the_rota(self, client: AsyncClient) -> None:
        """A consultant away for six months should not have to type their
        week out again when they come back."""
        await sign_up(client)
        doctor = await add(client)
        await set_schedule(client, doctor["id"], [block(MONDAY), block(TUESDAY)])

        await client.post(f"{API}/doctors/{doctor['id']}/deactivate")
        restored = (await client.post(f"{API}/doctors/{doctor['id']}/restore")).json()["data"]

        assert restored["status"] == "active"
        assert len(restored["schedule"]) == 2

    async def test_an_inactive_doctor_refuses_edits(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)
        await client.post(f"{API}/doctors/{doctor['id']}/deactivate")

        refused = await client.patch(f"{API}/doctors/{doctor['id']}", json={"room": "4"})
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "DOCTOR_INACTIVE"

    async def test_and_refuses_a_new_rota(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)
        await client.post(f"{API}/doctors/{doctor['id']}/deactivate")

        refused = await set_schedule(client, doctor["id"], [block(MONDAY)])
        assert refused.status_code == 409


class TestOtherClinics:
    async def test_another_clinics_doctor_is_not_found(self, client: AsyncClient) -> None:
        await sign_up(client)
        theirs = await add(client)
        await client.post(f"{AUTH}/logout")
        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("owner"))

        for path, method in (
            (f"{API}/doctors/{theirs['id']}", "get"),
            (f"{API}/doctors/{theirs['id']}/schedule", "get"),
            (f"{API}/doctors/{theirs['id']}/availability", "get"),
        ):
            response = await getattr(client, method)(path)
            assert response.status_code == 404, path
            assert response.json()["error"]["code"] == "DOCTOR_NOT_FOUND"

    async def test_and_cannot_be_edited_or_given_a_rota(self, client: AsyncClient) -> None:
        await sign_up(client)
        theirs = await add(client)
        await client.post(f"{AUTH}/logout")
        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("owner"))

        edited = await client.patch(f"{API}/doctors/{theirs['id']}", json={"room": "9"})
        assert edited.status_code == 404

        rota = await set_schedule(client, theirs["id"], [block(MONDAY)])
        assert rota.status_code == 404

        stood_down = await client.post(f"{API}/doctors/{theirs['id']}/deactivate")
        assert stood_down.status_code == 404

    async def test_and_does_not_show_up_in_a_search(self, client: AsyncClient) -> None:
        await sign_up(client)
        await add(client, first_name="Ananya", last_name="Iyer")
        await client.post(f"{AUTH}/logout")
        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("owner"))

        page = await listing(client, q="Ananya", status="all")
        assert page["total"] == 0


class TestWhoMayDoWhat:
    async def test_a_receptionist_can_see_doctors_but_not_change_them(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        """Booking starts by choosing a doctor, so reading is open to
        everyone who books. Setting a fee is not."""
        await sign_up(client)
        doctor = await add(client)
        joiner = await invite_and_accept(client, role="receptionist", outbox=outbox)
        await sign_in(client, joiner)

        readable = await client.get(f"{API}/doctors/{doctor['id']}")
        assert readable.status_code == 200

        refused = await client.patch(
            f"{API}/doctors/{doctor['id']}", json={"consultation_fee": "10.00"}
        )
        assert refused.status_code == 403

    async def test_a_doctor_cannot_write_their_own_rota(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        subject = await add(client)
        joiner = await invite_and_accept(client, role="doctor", outbox=outbox)
        await sign_in(client, joiner)

        refused = await set_schedule(client, subject["id"], [block(MONDAY)])
        assert refused.status_code == 403

    async def test_signed_out_reaches_nothing(self, client: AsyncClient) -> None:
        await sign_up(client)
        doctor = await add(client)
        await client.post(f"{AUTH}/logout")

        response = await client.get(f"{API}/doctors/{doctor['id']}")
        assert response.status_code == 401
