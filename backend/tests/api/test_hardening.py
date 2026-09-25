"""What every answer carries, and changes sent from somebody else's page."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.services import search as search_service
from tests.api.test_clinic import sign_up

API = "/api/v1"
ELSEWHERE = "https://clinic-portal.example.net"
NOTHING_LOADS = "default-src 'none'; frame-ancestors 'none'"


def own_origin() -> str:
    return sorted(get_settings().origins)[0]


class TestWhereAChangeComesFrom:
    async def test_a_change_from_another_site_is_refused_before_it_runs(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)

        response = await client.post(
            f"{API}/patients",
            json={"first_name": "Rhea", "last_name": "Kapoor", "phone": "9820077441"},
            headers={"Origin": ELSEWHERE},
        )
        listed = (await client.get(f"{API}/patients")).json()["data"]

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ORIGIN_REFUSED"
        assert listed["total"] == 0

    async def test_the_application_s_own_page_is_let_through(self, client: AsyncClient) -> None:
        await sign_up(client)

        response = await client.post(
            f"{API}/patients",
            json={
                "first_name": "Rhea",
                "last_name": "Kapoor",
                "phone": "9820077441",
                "gender": "female",
            },
            headers={"Origin": own_origin()},
        )

        assert response.status_code == 201, response.text

    async def test_reading_from_anywhere_is_left_to_the_session(
        self, client: AsyncClient
    ) -> None:
        await sign_up(client)

        response = await client.get(f"{API}/patients", headers={"Origin": ELSEWHERE})

        assert response.status_code == 200

    async def test_a_request_with_no_origin_is_judged_on_its_session(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(f"{API}/patients", json={"first_name": "Rhea"})

        assert response.status_code == 401

    async def test_the_payment_webhook_is_not_asked_where_it_came_from(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            f"{API}/pay/webhook/razorpay",
            content=b"{}",
            headers={"Origin": ELSEWHERE, "Content-Type": "application/json"},
        )

        assert response.json()["error"]["code"] != "ORIGIN_REFUSED"

    async def test_a_second_address_can_be_trusted(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "trusted_origins", f"{ELSEWHERE}, ")

        response = await client.post(
            f"{API}/auth/login",
            json={"email": "nobody@example.org", "password": "not the password at all"},
            headers={"Origin": ELSEWHERE},
        )

        assert response.status_code == 401


class TestHeaders:
    async def test_every_answer_is_kept_out_of_frames_and_caches(
        self, client: AsyncClient
    ) -> None:
        for response in (
            await client.get(f"{API}/health"),
            await client.get(f"{API}/patients"),
            await client.get(f"{API}/no-such-route"),
        ):
            headers = response.headers
            assert headers["x-content-type-options"] == "nosniff"
            assert headers["x-frame-options"] == "DENY"
            assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
            assert headers["cache-control"] == "no-store"
            assert headers["content-security-policy"] == NOTHING_LOADS


class TestWhenSomethingBreaks:
    async def test_the_person_gets_an_id_to_quote_and_nothing_of_the_inside(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await sign_up(client)
        cookies = dict(client.cookies)

        async def broken(*_: object, **__: object) -> None:
            raise RuntimeError("relation patients_secret does not exist")

        monkeypatch.setattr(search_service, "find", broken)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="https://testserver", cookies=cookies
        ) as fresh:
            response = await fresh.get(f"{API}/search", params={"q": "rhea"})

        error = response.json()["error"]
        assert response.status_code == 500
        assert error["code"] == "INTERNAL_ERROR"
        assert error["request_id"] == response.headers["x-request-id"]
        assert "patients_secret" not in response.text
