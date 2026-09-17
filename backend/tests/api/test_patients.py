"""Patient records: registering, finding, correcting and archiving them.

The duplicate cases carry the most weight. A clinic that splits one person
across two records loses half their history at the moment somebody needs it,
and the same clinic merging two people into one record is worse still, so
what is tested here is that the system asks rather than decides.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from httpx import AsyncClient

from tests.api.test_clinic import invite_and_accept, sign_in, sign_up
from tests.conftest import Outbox, unique_email

API = "/api/v1"
AUTH = "/api/v1/auth"


def details(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "first_name": "Aarti",
        "last_name": "Deshmukh",
        "phone": "9820011223",
        "date_of_birth": "1988-04-12",
        "gender": "female",
    }
    body.update(overrides)
    return body


async def register(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/patients", json=details(**overrides))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()["data"]
    return created


async def listing(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/patients", params=params)
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()["data"]
    return page


class TestRegistering:
    async def test_the_first_patient_is_numbered_from_one(self, client: AsyncClient) -> None:
        await sign_up(client)
        patient = await register(client)

        assert patient["patient_number"] == "PT-000001"
        assert patient["full_name"] == "Aarti Deshmukh"
        assert patient["status"] == "active"

    async def test_numbers_run_in_sequence(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client)
        second = await register(client, first_name="Rohit", phone="9820011224")

        assert second["patient_number"] == "PT-000002"

    async def test_each_clinic_counts_from_its_own_one(self, client: AsyncClient) -> None:
        """The number is what a receptionist reads off a card. It would be
        strange, and would leak the platform's size, if the first patient at
        a new clinic were PT-004312."""
        await sign_up(client)
        await register(client)
        await client.post(f"{AUTH}/logout")

        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("owner"))
        theirs = await register(client)

        assert theirs["patient_number"] == "PT-000001"

    async def test_age_is_derived_not_stored(self, client: AsyncClient) -> None:
        await sign_up(client)
        born = dt.date.today().replace(year=dt.date.today().year - 34)
        patient = await register(client, date_of_birth=born.isoformat())

        assert patient["age"] == "34 y"

    async def test_an_infant_is_described_in_months(self, client: AsyncClient) -> None:
        await sign_up(client)
        born = dt.date.today() - dt.timedelta(days=200)
        patient = await register(client, date_of_birth=born.isoformat())

        assert patient["age"].endswith("mo")

    async def test_a_phone_number_is_stored_without_its_punctuation(
        self, client: AsyncClient
    ) -> None:
        """Two records that differ only by a dash are two records as far as
        duplicate detection is concerned."""
        await sign_up(client)
        patient = await register(client, phone="+91 98200-11223")

        assert patient["phone"] == "+919820011223"

    async def test_who_registered_the_record_is_kept(self, client: AsyncClient) -> None:
        session = await sign_up(client)
        patient = await register(client)

        detail = (await client.get(f"{API}/patients/{patient['id']}")).json()["data"]
        assert detail["registered_by_name"] == (
            f"{session['user']['first_name']} {session['user']['last_name']}"
        )


class TestValidation:
    async def test_a_birth_date_in_the_future_is_refused(self, client: AsyncClient) -> None:
        await sign_up(client)
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        response = await client.post(f"{API}/patients", json=details(date_of_birth=tomorrow))

        assert response.status_code == 422
        assert "date_of_birth" in response.json()["error"]["fields"]

    async def test_a_phone_number_too_short_to_dial_is_refused(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        response = await client.post(f"{API}/patients", json=details(phone="12345"))

        assert response.status_code == 422
        assert "phone" in response.json()["error"]["fields"]

    async def test_a_name_is_required(self, client: AsyncClient) -> None:
        await sign_up(client)
        response = await client.post(f"{API}/patients", json=details(first_name=""))

        assert response.status_code == 422

    async def test_a_gender_outside_the_set_is_refused(self, client: AsyncClient) -> None:
        await sign_up(client)
        response = await client.post(f"{API}/patients", json=details(gender="banana"))

        assert response.status_code == 422

    async def test_a_patient_with_no_phone_or_birthday_is_still_valid(
        self, client: AsyncClient
    ) -> None:
        """A walk-in with no phone is a normal afternoon, and refusing to
        register them would push staff into inventing numbers."""
        await sign_up(client)
        patient = await register(client, phone=None, date_of_birth=None)

        assert patient["age"] is None
        assert patient["phone"] is None


class TestDuplicates:
    async def test_the_same_phone_number_stops_a_second_registration(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        first = await register(client)

        response = await client.post(
            f"{API}/patients", json=details(first_name="A.", last_name="Deshmukh")
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "PATIENT_DUPLICATE_SUSPECTED"
        assert error["candidates"][0]["id"] == first["id"]
        assert error["candidates"][0]["reason"] == "Same phone number"

    async def test_the_same_name_and_birthday_is_flagged(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client)

        response = await client.post(f"{API}/patients", json=details(phone="9812345678"))
        assert response.status_code == 409
        assert response.json()["error"]["candidates"][0]["reason"] == (
            "Same name and date of birth"
        )

    async def test_confirming_registers_them_anyway(self, client: AsyncClient) -> None:
        """Two people do share a handset. The person at the desk is the only
        one who can tell a family from a double entry."""
        await sign_up(client)
        await register(client)

        second = await register(client, first_name="Rohit", confirm_duplicate=True)
        assert second["patient_number"] == "PT-000002"

    async def test_a_different_person_is_not_flagged(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client)

        response = await client.post(
            f"{API}/patients",
            json=details(first_name="Sunil", last_name="Kulkarni", phone="9123456780"),
        )
        assert response.status_code == 201

    async def test_the_check_runs_before_the_form_is_submitted(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        existing = await register(client)

        response = await client.post(
            f"{API}/patients/check-duplicates", json={"phone": "98200-11223"}
        )
        assert response.status_code == 200
        candidates = response.json()["data"]
        assert [row["id"] for row in candidates] == [existing["id"]]

    async def test_an_archived_record_still_surfaces(self, client: AsyncClient) -> None:
        """Somebody returning after two years is the case archiving exists
        for. Hiding them here would produce a second record for the person
        whose first one is one click from being restored."""
        await sign_up(client)
        existing = await register(client)
        await client.post(f"{API}/patients/{existing['id']}/archive")

        response = await client.post(
            f"{API}/patients/check-duplicates", json={"phone": "9820011223"}
        )
        candidates = response.json()["data"]
        assert [row["status"] for row in candidates] == ["archived"]

    async def test_a_record_is_never_its_own_duplicate(self, client: AsyncClient) -> None:
        await sign_up(client)
        existing = await register(client)

        response = await client.post(
            f"{API}/patients/check-duplicates",
            json={"phone": "9820011223", "exclude_id": existing["id"]},
        )
        assert response.json()["data"] == []


class TestFinding:
    async def test_a_misheard_name_still_finds_them(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client, first_name="Aarti", last_name="Deshmukh")

        page = await listing(client, q="arti deshmuk")
        assert [row["full_name"] for row in page["items"]] == ["Aarti Deshmukh"]

    async def test_part_of_a_surname_finds_them(self, client: AsyncClient) -> None:
        """The common case at a desk: somebody reads out half a name. It is
        matched against the closest run of words rather than against the
        whole name, or a surname would score too low to find anybody."""
        await sign_up(client)
        await register(client, first_name="Rajesh", last_name="Krishnamurthy")

        assert (await listing(client, q="krishnamurty"))["total"] == 1
        assert (await listing(client, q="Krishna"))["total"] == 1

    async def test_an_unrelated_name_is_not_dragged_in(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client, first_name="Rajesh", last_name="Krishnamurthy")

        assert (await listing(client, q="Fernandes"))["total"] == 0

    async def test_a_phone_number_finds_them(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client)

        page = await listing(client, q="0011223")
        assert page["total"] == 1

    async def test_a_patient_number_finds_them(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client)

        page = await listing(client, q="PT-000001")
        assert page["total"] == 1

    async def test_the_closest_match_comes_first(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(
            client,
            first_name="Anil",
            last_name="Kapoor",
            phone="9000000001",
            date_of_birth="1971-02-03",
        )
        await register(
            client,
            first_name="Anita",
            last_name="Kapoor",
            phone="9000000002",
            date_of_birth="1994-11-30",
        )

        page = await listing(client, q="Anita Kapoor")
        assert page["items"][0]["full_name"] == "Anita Kapoor"

    async def test_nothing_matching_is_an_empty_page_not_an_error(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        await register(client)

        page = await listing(client, q="zzzzzz")
        assert page == {"items": [], "total": 0, "page": 1, "per_page": 25, "pages": 1}

    async def test_a_wildcard_is_searched_for_literally(self, client: AsyncClient) -> None:
        """Otherwise typing % into the box returns the whole register, which
        is surprising rather than dangerous, but still wrong."""
        await sign_up(client)
        await register(client)

        assert (await listing(client, q="%"))["total"] == 0
        assert (await listing(client, q="_"))["total"] == 0

    async def test_the_list_is_paged(self, client: AsyncClient) -> None:
        await sign_up(client)
        for index in range(5):
            await register(
                client,
                first_name=f"Person{index}",
                last_name="Sharma",
                phone=f"90000000{index:02d}",
                date_of_birth=None,
            )

        first = await listing(client, per_page=2)
        second = await listing(client, per_page=2, page=2)

        assert first["total"] == 5
        assert first["pages"] == 3
        assert len(first["items"]) == 2
        assert {row["id"] for row in first["items"]}.isdisjoint(
            {row["id"] for row in second["items"]}
        )

    async def test_paging_never_repeats_somebody_registered_in_the_same_second(
        self, client: AsyncClient
    ) -> None:
        """Rows created together share a created_at, and an order with ties
        is not an order — the second page can show what the first already
        did, which reads as a duplicate record that does not exist."""
        await sign_up(client)
        for index in range(6):
            await register(
                client,
                first_name=f"Same{index}",
                last_name="Second",
                phone=None,
                date_of_birth=None,
            )

        seen: list[str] = []
        for page in (1, 2, 3):
            found = await listing(client, per_page=2, page=page)
            seen += [row["id"] for row in found["items"]]

        assert len(seen) == 6
        assert len(set(seen)) == 6

    async def test_a_page_past_the_end_is_empty_rather_than_an_error(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        await register(client)

        far = await listing(client, page=99)
        assert far["items"] == []
        assert far["total"] == 1

    async def test_an_empty_register_is_an_empty_page(self, client: AsyncClient) -> None:
        await sign_up(client)
        assert await listing(client) == {
            "items": [],
            "total": 0,
            "page": 1,
            "per_page": 25,
            "pages": 1,
        }


class TestArchiving:
    async def test_archiving_takes_them_out_of_the_day_to_day_list(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        patient = await register(client)

        archived = await client.post(f"{API}/patients/{patient['id']}/archive")
        assert archived.status_code == 200
        assert archived.json()["data"]["status"] == "archived"

        assert (await listing(client))["total"] == 0
        assert (await listing(client, status="archived"))["total"] == 1
        assert (await listing(client, status="all"))["total"] == 1

    async def test_the_record_itself_is_still_there(self, client: AsyncClient) -> None:
        """Archiving hides a record. Nothing that hangs off it is deleted,
        and the record is still readable by id."""
        await sign_up(client)
        patient = await register(client)
        await client.post(f"{API}/patients/{patient['id']}/archive")

        found = await client.get(f"{API}/patients/{patient['id']}")
        assert found.status_code == 200
        assert found.json()["data"]["archived_at"] is not None

    async def test_an_archived_record_refuses_edits_until_it_is_restored(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        patient = await register(client)
        await client.post(f"{API}/patients/{patient['id']}/archive")

        refused = await client.patch(
            f"{API}/patients/{patient['id']}", json={"phone": "9000000000"}
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "PATIENT_ARCHIVED"

        await client.post(f"{API}/patients/{patient['id']}/restore")
        allowed = await client.patch(
            f"{API}/patients/{patient['id']}", json={"phone": "9000000000"}
        )
        assert allowed.status_code == 200
        assert allowed.json()["data"]["phone"] == "9000000000"


class TestCorrecting:
    async def test_one_field_can_be_changed_without_resending_the_rest(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        patient = await register(client)

        response = await client.patch(
            f"{API}/patients/{patient['id']}", json={"phone": "9812345678"}
        )
        updated = response.json()["data"]

        assert updated["phone"] == "9812345678"
        assert updated["first_name"] == "Aarti"
        assert updated["date_of_birth"] == "1988-04-12"

    async def test_an_address_is_replaced_whole(self, client: AsyncClient) -> None:
        await sign_up(client)
        patient = await register(client)
        await client.patch(
            f"{API}/patients/{patient['id']}",
            json={"address": {"line1": "22 Hill Road", "city": "Bandra"}},
        )
        response = await client.patch(
            f"{API}/patients/{patient['id']}",
            json={"address": {"line1": "9 Carter Road", "city": "Khar"}},
        )

        address = response.json()["data"]["address"]
        assert address["line1"] == "9 Carter Road"
        assert address["city"] == "Khar"

    async def test_a_correction_is_still_validated(self, client: AsyncClient) -> None:
        await sign_up(client)
        patient = await register(client)

        response = await client.patch(f"{API}/patients/{patient['id']}", json={"phone": "12"})
        assert response.status_code == 422


class TestAllergies:
    async def test_an_allergy_is_recorded_against_the_person(self, client: AsyncClient) -> None:
        await sign_up(client)
        patient = await register(client)

        response = await client.post(
            f"{API}/patients/{patient['id']}/allergies",
            json={"substance": "Penicillin", "reaction": "Rash", "severity": "severe"},
        )
        assert response.status_code == 201

        detail = (await client.get(f"{API}/patients/{patient['id']}")).json()["data"]
        assert detail["allergies"][0]["substance"] == "Penicillin"
        assert detail["allergy_count"] == 1

    async def test_the_dangerous_one_is_listed_first(self, client: AsyncClient) -> None:
        await sign_up(client)
        patient = await register(client)
        for substance, severity in (("Dust", "mild"), ("Sulfa", "severe")):
            await client.post(
                f"{API}/patients/{patient['id']}/allergies",
                json={"substance": substance, "severity": severity},
            )

        detail = (await client.get(f"{API}/patients/{patient['id']}")).json()["data"]
        assert [row["substance"] for row in detail["allergies"]] == ["Sulfa", "Dust"]

    async def test_the_same_substance_is_not_recorded_twice(self, client: AsyncClient) -> None:
        await sign_up(client)
        patient = await register(client)
        await client.post(
            f"{API}/patients/{patient['id']}/allergies", json={"substance": "Penicillin"}
        )

        again = await client.post(
            f"{API}/patients/{patient['id']}/allergies", json={"substance": "penicillin"}
        )
        assert again.status_code == 422

    async def test_one_can_be_taken_off_the_list(self, client: AsyncClient) -> None:
        await sign_up(client)
        patient = await register(client)
        added = await client.post(
            f"{API}/patients/{patient['id']}/allergies", json={"substance": "Latex"}
        )
        allergy_id = added.json()["data"]["id"]

        removed = await client.delete(f"{API}/patients/{patient['id']}/allergies/{allergy_id}")
        assert removed.status_code == 200

        detail = (await client.get(f"{API}/patients/{patient['id']}")).json()["data"]
        assert detail["allergies"] == []

    async def test_an_allergy_belonging_to_another_patient_is_not_found(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        theirs = await register(client)
        somebody_else = await register(client, first_name="Rohit", phone="9123456789")
        added = await client.post(
            f"{API}/patients/{theirs['id']}/allergies", json={"substance": "Latex"}
        )

        response = await client.delete(
            f"{API}/patients/{somebody_else['id']}/allergies/{added.json()['data']['id']}"
        )
        assert response.status_code == 404


class TestTenancy:
    """The checks that matter most in a system holding two clinics' records."""

    async def test_another_clinics_patient_is_not_found(self, client: AsyncClient) -> None:
        await sign_up(client)
        theirs = await register(client)
        await client.post(f"{AUTH}/logout")

        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("other"))
        response = await client.get(f"{API}/patients/{theirs['id']}")

        # 404, not 403. A 403 would confirm the record exists, and an id is
        # guessable enough that confirming would map the other clinic.
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PATIENT_NOT_FOUND"

    async def test_another_clinics_patient_cannot_be_edited(self, client: AsyncClient) -> None:
        await sign_up(client)
        theirs = await register(client)
        await client.post(f"{AUTH}/logout")

        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("other"))
        response = await client.patch(
            f"{API}/patients/{theirs['id']}", json={"first_name": "Changed"}
        )
        assert response.status_code == 404

    async def test_another_clinics_patient_cannot_be_archived(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        theirs = await register(client)
        await client.post(f"{AUTH}/logout")

        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("other"))
        assert (await client.post(f"{API}/patients/{theirs['id']}/archive")).status_code == 404

    async def test_a_search_never_reaches_across(self, client: AsyncClient) -> None:
        await sign_up(client)
        await register(client)
        await client.post(f"{AUTH}/logout")

        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("other"))
        assert (await listing(client, q="Deshmukh"))["total"] == 0

    async def test_a_duplicate_check_never_reaches_across(self, client: AsyncClient) -> None:
        """Otherwise the check becomes a way to ask whether a phone number is
        registered at any clinic on the platform."""
        await sign_up(client)
        await register(client)
        await client.post(f"{AUTH}/logout")

        await sign_up(client, clinic_name="Northgate Clinic", email=unique_email("other"))
        response = await client.post(
            f"{API}/patients/check-duplicates", json={"phone": "9820011223"}
        )
        assert response.json()["data"] == []


class TestWhoCanDoWhat:
    async def test_a_doctor_can_register_and_correct(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        doctor = await invite_and_accept(client, role="doctor", outbox=outbox)
        await client.post(f"{AUTH}/logout")
        await sign_in(client, doctor)

        patient = await register(client)
        response = await client.patch(
            f"{API}/patients/{patient['id']}", json={"notes": "Seen for a cough."}
        )
        assert response.status_code == 200

    async def test_a_doctor_cannot_archive(self, client: AsyncClient, outbox: Outbox) -> None:
        """Archiving is an administrative decision about the register, not a
        clinical one about the patient."""
        await sign_up(client)
        patient = await register(client)
        doctor = await invite_and_accept(client, role="doctor", outbox=outbox)
        await client.post(f"{AUTH}/logout")
        await sign_in(client, doctor)

        response = await client.post(f"{API}/patients/{patient['id']}/archive")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    async def test_general_staff_can_read_but_not_register(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        await register(client)
        member = await invite_and_accept(client, role="staff", outbox=outbox)
        await client.post(f"{AUTH}/logout")
        await sign_in(client, member)

        assert (await listing(client))["total"] == 1
        assert (await client.post(f"{API}/patients", json=details())).status_code == 403

    async def test_signing_out_closes_the_register(self, client: AsyncClient) -> None:
        await sign_up(client)
        await client.post(f"{AUTH}/logout")

        assert (await client.get(f"{API}/patients")).status_code == 401
