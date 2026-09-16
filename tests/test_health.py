"""The health endpoint is the one thing that must never lie."""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from backend.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_reports_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"


async def test_every_response_carries_a_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.headers.get("X-Request-Id")


async def test_unknown_route_uses_the_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/nothing-here")
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_health_does_not_leak_connection_details(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/health")).json()["data"]
    serialised = str(body)
    assert "password" not in serialised.lower()
    assert "@" not in serialised
