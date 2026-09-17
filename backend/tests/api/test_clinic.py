"""Clinic setup, staff, and the invitations that add them.

The tenancy checks matter most here. This is the first work where one
clinic's rows could be reached from another, so several of these exist to
prove they cannot be.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import GOOD_PASSWORD, Outbox, registration, unique_email

AUTH = "/api/v1/auth"
API = "/api/v1"


async def sign_up(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    """A clinic and its administrator, signed in."""
    response = await client.post(f"{AUTH}/register", json=registration(**overrides))
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()["data"]["session"]
    return payload


async def sign_in(client: AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        f"{AUTH}/login", json={"email": email, "password": GOOD_PASSWORD}
    )
    assert response.status_code == 200, response.text
    session: dict[str, Any] = response.json()["data"]
    return session


async def someone_else(client: AsyncClient) -> dict[str, Any]:
    """The one member of staff who is not the caller."""
    listing = (await client.get(f"{API}/staff")).json()["data"]
    return next(member for member in listing if not member["is_you"])


async def set_up_clinic(client: AsyncClient) -> None:
    await client.patch(
        f"{API}/clinic",
        json={
            "phone": "+91 22 5555 0100",
            "address": {"line1": "14 Marine Lines", "city": "Mumbai", "state": "Maharashtra"},
        },
    )


class TestClinicDetails:
    async def test_a_new_clinic_is_pending_until_setup_finishes(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        clinic = (await client.get(f"{API}/clinic")).json()["data"]

        assert clinic["status"] == "pending"
        assert clinic["onboarding_completed_at"] is None
        assert (await client.get(f"{API}/clinic/needs-setup")).json()["data"]["needs_setup"]

    async def test_details_can_be_filled_in(self, client: AsyncClient) -> None:
        await sign_up(client)
        response = await client.patch(
            f"{API}/clinic",
            json={
                "phone": "+91 22 5555 0100",
                "address": {"line1": "14 Marine Lines", "city": "Mumbai"},
            },
        )
        clinic = response.json()["data"]
        assert clinic["phone"] == "+91 22 5555 0100"
        assert clinic["address"]["city"] == "Mumbai"
        # Untouched fields keep what they had.
        assert clinic["timezone"] == "Asia/Kolkata"

    async def test_setup_is_refused_while_the_essentials_are_missing(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        response = await client.post(f"{API}/clinic/complete-setup")

        assert response.status_code == 422
        fields = response.json()["error"]["fields"]
        assert "phone" in fields
        assert "address" in fields

    async def test_setup_opens_the_clinic(self, client: AsyncClient) -> None:
        await sign_up(client)
        await set_up_clinic(client)

        clinic = (await client.post(f"{API}/clinic/complete-setup")).json()["data"]
        assert clinic["status"] == "active"
        assert clinic["onboarding_completed_at"] is not None
        assert (await client.get(f"{API}/clinic/needs-setup")).json()["data"][
            "needs_setup"
        ] is False


class TestSettings:
    async def test_defaults_are_returned_before_anything_is_set(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)
        settings = (await client.get(f"{API}/clinic/settings")).json()["data"]

        assert settings["consultation_duration_minutes"] == 15
        assert settings["invoice_prefix"] == "INV"

    async def test_money_survives_as_a_string(self, client: AsyncClient) -> None:
        """A JSON number is a double, and a double cannot hold 0.1 + 0.2.
        Fees are not a place to find that out."""
        await sign_up(client)
        response = await client.patch(
            f"{API}/clinic/settings", json={"consultation_fee": "450.50"}
        )
        assert response.json()["data"]["consultation_fee"] == "450.50"

    async def test_one_change_does_not_wipe_the_others(self, client: AsyncClient) -> None:
        await sign_up(client)
        await client.patch(f"{API}/clinic/settings", json={"consultation_fee": "450.00"})
        settings = (
            await client.patch(f"{API}/clinic/settings", json={"invoice_prefix": "SUN"})
        ).json()["data"]

        assert settings["invoice_prefix"] == "SUN"
        assert settings["consultation_fee"] == "450.00"

    @pytest.mark.parametrize(
        "payload",
        [
            {"consultation_duration_minutes": 2},
            {"consultation_duration_minutes": 500},
            {"consultation_fee": "-10.00"},
            {"tax_percent": "120.00"},
        ],
    )
    async def test_nonsense_is_refused(
        self, client: AsyncClient, payload: dict[str, Any]
    ) -> None:
        await sign_up(client)
        assert (await client.patch(f"{API}/clinic/settings", json=payload)).status_code == 422


class TestPermissions:
    async def test_a_receptionist_cannot_change_settings_or_see_staff(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        joiner = await invite_and_accept(client, role="receptionist", outbox=outbox)

        await client.post(f"{AUTH}/logout")
        await client.post(f"{AUTH}/login", json={"email": joiner, "password": GOOD_PASSWORD})

        # Reading the clinic is fine: a receptionist needs its name.
        assert (await client.get(f"{API}/clinic")).status_code == 200

        refused = await client.patch(f"{API}/clinic", json={"phone": "+91 99999 99999"})
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

        assert (await client.get(f"{API}/staff")).status_code == 403
        assert (
            await client.post(
                f"{API}/staff/invitations",
                json={
                    "email": unique_email(),
                    "first_name": "A",
                    "last_name": "B",
                    "role_slug": "doctor",
                },
            )
        ).status_code == 403

    async def test_signed_out_callers_are_turned_away(self, client: AsyncClient) -> None:
        for path in ("/clinic", "/clinic/settings", "/staff", "/staff/invitations"):
            response = await client.get(f"{API}{path}")
            assert response.status_code == 401, path


async def invite_and_accept(
    client: AsyncClient, *, role: str, outbox: Outbox, email: str | None = None
) -> str:
    """Invites somebody and redeems the link, returning their address."""
    address = email or unique_email("joiner")
    sent = await client.post(
        f"{API}/staff/invitations",
        json={
            "email": address,
            "first_name": "Joiner",
            "last_name": "Person",
            "role_slug": role,
        },
    )
    assert sent.status_code == 201, sent.text

    accepted = await client.post(
        f"{API}/invitations/accept",
        json={"token": outbox.latest_token(), "password": GOOD_PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    return address


class TestInvitations:
    async def test_an_invited_person_joins_the_existing_clinic(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        owner = await sign_up(client, clinic_name="Harbour Road Clinic")
        joiner = await invite_and_accept(client, role="doctor", outbox=outbox)

        await client.post(f"{AUTH}/logout")
        session = await sign_in(client, joiner)

        # The same clinic, not a new one. This is the whole point.
        assert session["organization"]["id"] == owner["organization"]["id"]
        assert session["organization"]["name"] == "Harbour Road Clinic"
        assert session["role"] == "doctor"

    async def test_the_invitation_decides_the_role_not_the_request(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        """Holding a link must not be a way to award yourself a role."""
        await sign_up(client)
        address = unique_email("joiner")
        await client.post(
            f"{API}/staff/invitations",
            json={
                "email": address,
                "first_name": "J",
                "last_name": "P",
                "role_slug": "receptionist",
            },
        )
        token = outbox.latest_token()

        await client.post(
            f"{API}/invitations/accept",
            json={"token": token, "password": GOOD_PASSWORD, "role_slug": "clinic-admin"},
        )

        await client.post(f"{AUTH}/logout")
        session = await sign_in(client, address)
        assert session["role"] == "receptionist"

    async def test_the_link_goes_to_the_invited_address(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = unique_email("joiner")
        await client.post(
            f"{API}/staff/invitations",
            json={"email": address, "first_name": "J", "last_name": "P", "role_slug": "doctor"},
        )
        assert outbox.recipients[-1] == address

    async def test_an_invitation_works_only_once(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        await client.post(
            f"{API}/staff/invitations",
            json={
                "email": unique_email("joiner"),
                "first_name": "J",
                "last_name": "P",
                "role_slug": "doctor",
            },
        )
        token = outbox.latest_token()

        assert (
            await client.post(
                f"{API}/invitations/accept", json={"token": token, "password": GOOD_PASSWORD}
            )
        ).status_code == 200

        again = await client.post(
            f"{API}/invitations/accept", json={"token": token, "password": GOOD_PASSWORD}
        )
        assert again.json()["error"]["code"] == "INVITATION_INVALID"

    async def test_a_made_up_link_says_nothing(self, client: AsyncClient) -> None:
        response = await client.get(f"{API}/invitations/not-a-real-token")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVITATION_INVALID"

    async def test_the_preview_shows_the_clinic_and_role_and_no_more(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client, clinic_name="Lakeview Clinic")
        address = unique_email("joiner")
        await client.post(
            f"{API}/staff/invitations",
            json={
                "email": address,
                "first_name": "Asha",
                "last_name": "Rao",
                "role_slug": "doctor",
            },
        )
        token = outbox.latest_token()

        preview = (await client.get(f"{API}/invitations/{token}")).json()["data"]
        assert preview == {
            "clinic_name": "Lakeview Clinic",
            "role_name": "Doctor",
            "email": address,
            "first_name": "Asha",
        }

    async def test_inviting_the_same_address_twice_is_refused(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        address = unique_email("joiner")
        body = {
            "email": address,
            "first_name": "J",
            "last_name": "P",
            "role_slug": "doctor",
        }
        assert (await client.post(f"{API}/staff/invitations", json=body)).status_code == 201
        again = await client.post(f"{API}/staff/invitations", json=body)
        assert again.status_code == 409

    async def test_inviting_somebody_who_already_works_here_is_refused(
        self, client: AsyncClient
    ) -> None:
        owner = await sign_up(client)
        response = await client.post(
            f"{API}/staff/invitations",
            json={
                "email": owner["user"]["email"],
                "first_name": "J",
                "last_name": "P",
                "role_slug": "doctor",
            },
        )
        assert response.status_code == 409

    async def test_a_revoked_invitation_cannot_be_redeemed(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        await client.post(
            f"{API}/staff/invitations",
            json={
                "email": unique_email("joiner"),
                "first_name": "J",
                "last_name": "P",
                "role_slug": "doctor",
            },
        )
        token = outbox.latest_token()
        pending = (await client.get(f"{API}/staff/invitations")).json()["data"]
        assert len(pending) == 1

        await client.delete(f"{API}/staff/invitations/{pending[0]['id']}")

        assert (
            await client.post(
                f"{API}/invitations/accept", json={"token": token, "password": GOOD_PASSWORD}
            )
        ).json()["error"]["code"] == "INVITATION_INVALID"
        assert (await client.get(f"{API}/staff/invitations")).json()["data"] == []


class TestTenantIsolation:
    async def test_one_clinic_cannot_revoke_another_clinics_invitation(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        """A row from another clinic reads as absent, not as forbidden.
        Answering 403 would confirm it exists."""
        await sign_up(client, clinic_name="Clinic One")
        await client.post(
            f"{API}/staff/invitations",
            json={
                "email": unique_email("one"),
                "first_name": "J",
                "last_name": "P",
                "role_slug": "doctor",
            },
        )
        theirs = (await client.get(f"{API}/staff/invitations")).json()["data"][0]["id"]

        await client.post(f"{AUTH}/logout")
        await sign_up(client, clinic_name="Clinic Two")

        response = await client.delete(f"{API}/staff/invitations/{theirs}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    async def test_staff_listings_do_not_bleed_between_clinics(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        first = await sign_up(client, clinic_name="Clinic One")
        await invite_and_accept(client, role="doctor", outbox=outbox)
        assert len((await client.get(f"{API}/staff")).json()["data"]) == 2

        await client.post(f"{AUTH}/logout")
        second = await sign_up(client, clinic_name="Clinic Two")

        listing = (await client.get(f"{API}/staff")).json()["data"]
        assert len(listing) == 1
        assert listing[0]["email"] == second["user"]["email"]
        assert first["user"]["email"] not in [member["email"] for member in listing]

    async def test_another_clinics_member_cannot_be_suspended(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client, clinic_name="Clinic One")
        await invite_and_accept(client, role="doctor", outbox=outbox)
        theirs = (await someone_else(client))["id"]

        await client.post(f"{AUTH}/logout")
        await sign_up(client, clinic_name="Clinic Two")

        assert (await client.post(f"{API}/staff/{theirs}/suspend")).status_code == 404
        assert (
            await client.patch(f"{API}/staff/{theirs}/role", json={"role_slug": "staff"})
        ).status_code == 404


class TestStaffManagement:
    async def test_the_listing_marks_which_one_is_you(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        owner = await sign_up(client)
        await invite_and_accept(client, role="doctor", outbox=outbox)

        listing = (await client.get(f"{API}/staff")).json()["data"]
        me = [m for m in listing if m["is_you"]]
        assert len(me) == 1
        assert me[0]["email"] == owner["user"]["email"]

    async def test_a_role_can_be_changed(self, client: AsyncClient, outbox: Outbox) -> None:
        await sign_up(client)
        joiner = await invite_and_accept(client, role="staff", outbox=outbox)
        member = await someone_else(client)

        assert (
            await client.patch(f"{API}/staff/{member['id']}/role", json={"role_slug": "doctor"})
        ).status_code == 200

        await client.post(f"{AUTH}/logout")
        session = await sign_in(client, joiner)
        assert session["role"] == "doctor"

    async def test_the_last_administrator_cannot_be_demoted(self, client: AsyncClient) -> None:
        """Otherwise a clinic ends up with nobody able to run it."""
        owner = await sign_up(client)
        response = await client.patch(
            f"{API}/staff/{owner['user']['id']}/role", json={"role_slug": "doctor"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "LAST_ADMINISTRATOR"

    async def test_the_last_administrator_cannot_be_suspended(
        self, client: AsyncClient
    ) -> None:
        owner = await sign_up(client)
        response = await client.post(f"{API}/staff/{owner['user']['id']}/suspend")
        # Refused for being yourself before it is refused for being the last.
        assert response.status_code in (409, 422)

    async def test_a_second_administrator_frees_the_first(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        owner = await sign_up(client)
        await invite_and_accept(client, role="clinic-admin", outbox=outbox)

        response = await client.patch(
            f"{API}/staff/{owner['user']['id']}/role", json={"role_slug": "doctor"}
        )
        assert response.status_code == 200

    async def test_a_suspended_member_cannot_sign_in(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        joiner = await invite_and_accept(client, role="doctor", outbox=outbox)
        member = await someone_else(client)

        assert (await client.post(f"{API}/staff/{member['id']}/suspend")).status_code == 200

        await client.post(f"{AUTH}/logout")
        refused = await client.post(
            f"{AUTH}/login", json={"email": joiner, "password": GOOD_PASSWORD}
        )
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "ACCOUNT_SUSPENDED"

    async def test_restoring_lets_them_back_in(
        self, client: AsyncClient, outbox: Outbox
    ) -> None:
        await sign_up(client)
        joiner = await invite_and_accept(client, role="doctor", outbox=outbox)
        member = await someone_else(client)

        await client.post(f"{API}/staff/{member['id']}/suspend")
        await client.post(f"{API}/staff/{member['id']}/restore")

        await client.post(f"{AUTH}/logout")
        assert await sign_in(client, joiner)
