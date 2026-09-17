"""Sign-in, registration and recovery, exercised through the API.

These go through the real router and middleware rather than calling the
service directly, because several of the guarantees being checked here are
properties of the response: the cookies it sets, the headers it carries, and
the fact that two different situations produce the same body.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import GOOD_PASSWORD, FakeRedis, Outbox, registration, unique_email

AUTH = "/api/v1/auth"


async def register(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post(f"{AUTH}/register", json=registration(**overrides))
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()["data"]
    return payload


class TestRegistration:
    async def test_creates_the_clinic_and_makes_the_registrant_its_admin(
        self, client: AsyncClient
    ) -> None:
        data = await register(client, clinic_name="Harbour Road Clinic")
        session = data["session"]

        assert session["organization"]["name"] == "Harbour Road Clinic"
        assert session["role"] == "clinic-admin"
        # Setup has not happened yet, which is what the onboarding step is for.
        assert session["organization"]["status"] == "pending"
        assert session["organization"]["onboarding_completed_at"] is None

    async def test_admin_cannot_author_clinical_records(self, client: AsyncClient) -> None:
        data = await register(client)
        granted = set(data["session"]["permissions"])

        assert "staff:manage" in granted
        assert "consultation:read" in granted
        # The clinician who signs a note is the one accountable for it.
        assert "consultation:create" not in granted
        assert "consultation:update" not in granted
        assert "prescription:create" not in granted

    async def test_registration_cannot_mint_a_platform_account(
        self, client: AsyncClient
    ) -> None:
        data = await register(client)
        assert data["session"]["organization"] is not None
        assert "platform:manage" not in data["session"]["permissions"]

    async def test_session_travels_in_httponly_cookies_not_the_body(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(f"{AUTH}/register", json=registration())
        body = response.text

        assert "opd_access" in response.cookies
        assert "opd_refresh" in response.cookies
        # Nothing script on the page could read a token out of.
        assert "access_token" not in body
        assert "refresh_token" not in body

        raw = response.headers.get_list("set-cookie")
        assert all("HttpOnly" in cookie for cookie in raw)
        assert all("SameSite=lax" in cookie for cookie in raw)

    async def test_two_clinics_of_the_same_name_get_distinct_slugs(
        self, client: AsyncClient
    ) -> None:
        first = await register(client, clinic_name="Lakeview Clinic")
        second = await register(client, clinic_name="Lakeview Clinic")

        assert first["session"]["organization"]["slug"] == "lakeview-clinic"
        assert second["session"]["organization"]["slug"] == "lakeview-clinic-2"

    @pytest.mark.parametrize(
        "password",
        # Too short, then three that clear the length but are the first
        # things a credential-stuffing list tries.
        ["1234567", "12345678", "password123", "qwerty123"],
    )
    async def test_weak_passwords_are_refused(self, client: AsyncClient, password: str) -> None:
        response = await client.post(f"{AUTH}/register", json=registration(password=password))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "password" in response.json()["error"]["fields"]

    async def test_the_same_address_may_hold_an_account_at_two_clinics(
        self, client: AsyncClient
    ) -> None:
        shared = unique_email("anita")
        await register(client, clinic_name="Lakeview Clinic", email=shared)
        await register(client, clinic_name="Northgate Clinic", email=shared)


class TestSignIn:
    async def test_signs_in_with_the_right_password(self, client: AsyncClient) -> None:
        email = unique_email()
        await register(client, email=email)

        response = await client.post(
            f"{AUTH}/login", json={"email": email, "password": GOOD_PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["data"]["user"]["email"] == email

    async def test_address_is_matched_without_regard_to_case(self, client: AsyncClient) -> None:
        email = unique_email()
        await register(client, email=email)

        response = await client.post(
            f"{AUTH}/login", json={"email": email.upper(), "password": GOOD_PASSWORD}
        )
        assert response.status_code == 200

    async def test_a_wrong_password_and_an_unknown_address_answer_identically(
        self, client: AsyncClient
    ) -> None:
        email = unique_email()
        await register(client, email=email)

        wrong = await client.post(
            f"{AUTH}/login", json={"email": email, "password": "not the password"}
        )
        unknown = await client.post(
            f"{AUTH}/login",
            json={"email": unique_email("ghost"), "password": "not the password"},
        )

        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    async def test_five_failures_lock_the_address(
        self, client: AsyncClient, fake_redis: FakeRedis, outbox: Outbox
    ) -> None:
        email = unique_email()
        await register(client, email=email)

        # The fifth attempt is still answered normally and trips the lock;
        # the one after it is the first to be turned away.
        for _ in range(5):
            response = await client.post(
                f"{AUTH}/login", json={"email": email, "password": "wrong"}
            )
            assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

        response = await client.post(
            f"{AUTH}/login", json={"email": email, "password": "wrong"}
        )
        assert response.status_code == 423
        assert response.json()["error"]["code"] == "ACCOUNT_LOCKED"
        assert "Retry-After" in response.headers

        # Even the correct password is refused while the lock stands.
        blocked = await client.post(
            f"{AUTH}/login", json={"email": email, "password": GOOD_PASSWORD}
        )
        assert blocked.status_code == 423

        fake_redis.advance(16 * 60)
        allowed = await client.post(
            f"{AUTH}/login", json={"email": email, "password": GOOD_PASSWORD}
        )
        assert allowed.status_code == 200

    async def test_lockout_does_not_reveal_whether_the_address_exists(
        self, client: AsyncClient
    ) -> None:
        """An unknown address locks exactly like a real one, so the switch
        from one error to the other says nothing about who has an account."""
        ghost = unique_email("ghost")
        codes = []
        for _ in range(6):
            response = await client.post(
                f"{AUTH}/login", json={"email": ghost, "password": "wrong"}
            )
            codes.append(response.json()["error"]["code"])

        assert codes == ["INVALID_CREDENTIALS"] * 5 + ["ACCOUNT_LOCKED"]

    async def test_an_address_at_two_clinics_must_choose(self, client: AsyncClient) -> None:
        shared = unique_email("anita")
        await register(client, clinic_name="Lakeview Clinic", email=shared)
        await register(client, clinic_name="Northgate Clinic", email=shared)

        response = await client.post(
            f"{AUTH}/login", json={"email": shared, "password": GOOD_PASSWORD}
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "CLINIC_CHOICE_REQUIRED"
        assert {choice["slug"] for choice in error["choices"]} == {
            "lakeview-clinic",
            "northgate-clinic",
        }

        chosen = await client.post(
            f"{AUTH}/login",
            json={
                "email": shared,
                "password": GOOD_PASSWORD,
                "organization_slug": "northgate-clinic",
            },
        )
        assert chosen.json()["data"]["organization"]["name"] == "Northgate Clinic"

    async def test_the_clinic_list_is_not_given_away_before_the_password_is_proven(
        self, client: AsyncClient
    ) -> None:
        shared = unique_email("anita")
        await register(client, clinic_name="Lakeview Clinic", email=shared)
        await register(client, clinic_name="Northgate Clinic", email=shared)

        response = await client.post(
            f"{AUTH}/login", json={"email": shared, "password": "wrong"}
        )
        assert response.status_code == 401
        assert "choices" not in response.json()["error"]
        assert "lakeview" not in response.text.lower()


class TestSessionLifecycle:
    async def test_me_requires_a_session(self, client: AsyncClient) -> None:
        response = await client.get(f"{AUTH}/me")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "SESSION_EXPIRED"

    @pytest.mark.parametrize(
        "token",
        [
            "not.a.token",
            # A well-formed token signed with something else.
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDAiLCJleHAiOjk5OTk5OTk5OTl9."
            "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        ],
    )
    async def test_a_token_we_did_not_sign_is_refused(
        self, client: AsyncClient, token: str
    ) -> None:
        response = await client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "SESSION_EXPIRED"

    async def test_refresh_rotates_the_token(self, client: AsyncClient) -> None:
        await register(client)
        before = client.cookies.get("opd_refresh")

        response = await client.post(f"{AUTH}/refresh")
        assert response.status_code == 200
        assert client.cookies.get("opd_refresh") != before

    async def test_replaying_a_spent_refresh_token_kills_the_whole_family(
        self, client: AsyncClient
    ) -> None:
        await register(client)
        stolen = client.cookies.get("opd_refresh")

        await client.post(f"{AUTH}/refresh")
        current = client.cookies.get("opd_refresh")

        replay = await client.post(f"{AUTH}/refresh", cookies={"opd_refresh": stolen})
        assert replay.status_code == 401

        # The legitimate holder is signed out too. That is the intended
        # outcome: the alternative leaves an attacker with a live session.
        after = await client.post(f"{AUTH}/refresh", cookies={"opd_refresh": current})
        assert after.status_code == 401

    async def test_logout_ends_the_session(self, client: AsyncClient) -> None:
        await register(client)
        assert (await client.post(f"{AUTH}/logout")).status_code == 200
        assert (await client.post(f"{AUTH}/refresh")).status_code == 401


class TestRecovery:
    async def test_a_known_and_an_unknown_address_answer_identically(
        self, client: AsyncClient
    ) -> None:
        email = unique_email()
        await register(client, email=email)

        known = await client.post(f"{AUTH}/forgot-password", json={"email": email})
        unknown = await client.post(
            f"{AUTH}/forgot-password", json={"email": unique_email("ghost")}
        )

        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()

    async def test_the_response_never_carries_the_link(self, client: AsyncClient) -> None:
        email = unique_email()
        await register(client, email=email)
        response = await client.post(f"{AUTH}/forgot-password", json={"email": email})
        assert "token" not in response.text

    async def test_reset_replaces_the_password_and_spends_the_link(
        self, client: AsyncClient, fake_redis: FakeRedis, outbox: Outbox
    ) -> None:
        email = unique_email()
        await register(client, email=email)
        await client.post(f"{AUTH}/forgot-password", json={"email": email})
        token = outbox.latest_token()

        replacement = "an entirely different phrase"
        done = await client.post(
            f"{AUTH}/reset-password", json={"token": token, "password": replacement}
        )
        assert done.status_code == 200

        again = await client.post(
            f"{AUTH}/reset-password", json={"token": token, "password": replacement}
        )
        assert again.json()["error"]["code"] == "TOKEN_INVALID"

        assert (
            await client.post(f"{AUTH}/login", json={"email": email, "password": replacement})
        ).status_code == 200
        assert (
            await client.post(f"{AUTH}/login", json={"email": email, "password": GOOD_PASSWORD})
        ).status_code == 401

    async def test_a_rejected_password_leaves_the_link_usable(
        self, client: AsyncClient, fake_redis: FakeRedis, outbox: Outbox
    ) -> None:
        """Someone who fumbles the new password should not have to go back to
        their inbox for a fresh link."""
        email = unique_email()
        await register(client, email=email)
        await client.post(f"{AUTH}/forgot-password", json={"email": email})
        token = outbox.latest_token()

        refused = await client.post(
            f"{AUTH}/reset-password", json={"token": token, "password": "password123"}
        )
        assert refused.status_code == 422

        accepted = await client.post(
            f"{AUTH}/reset-password",
            json={"token": token, "password": "a second attempt entirely"},
        )
        assert accepted.status_code == 200

    async def test_an_expired_link_is_refused(
        self, client: AsyncClient, fake_redis: FakeRedis, outbox: Outbox
    ) -> None:
        email = unique_email()
        await register(client, email=email)
        await client.post(f"{AUTH}/forgot-password", json={"email": email})
        token = outbox.latest_token()

        fake_redis.advance(31 * 60)

        response = await client.post(
            f"{AUTH}/reset-password", json={"token": token, "password": "another long one"}
        )
        assert response.json()["error"]["code"] == "TOKEN_INVALID"

    async def test_a_made_up_link_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{AUTH}/reset-password",
            json={"token": "invented", "password": "a long enough password"},
        )
        assert response.json()["error"]["code"] == "TOKEN_INVALID"

    async def test_resetting_signs_out_every_other_session(
        self, client: AsyncClient, fake_redis: FakeRedis, outbox: Outbox
    ) -> None:
        email = unique_email()
        await register(client, email=email)
        elsewhere = client.cookies.get("opd_refresh")

        await client.post(f"{AUTH}/forgot-password", json={"email": email})
        token = outbox.latest_token()
        await client.post(
            f"{AUTH}/reset-password",
            json={"token": token, "password": "a brand new secret phrase"},
        )

        stale = await client.post(f"{AUTH}/refresh", cookies={"opd_refresh": elsewhere})
        assert stale.status_code == 401

    async def test_reset_requests_are_rate_limited_per_address(
        self, client: AsyncClient
    ) -> None:
        email = unique_email()
        await register(client, email=email)

        for _ in range(3):
            assert (
                await client.post(f"{AUTH}/forgot-password", json={"email": email})
            ).status_code == 200

        fourth = await client.post(f"{AUTH}/forgot-password", json={"email": email})
        assert fourth.status_code == 429
        assert fourth.json()["error"]["code"] == "RATE_LIMITED"
        assert "Retry-After" in fourth.headers
