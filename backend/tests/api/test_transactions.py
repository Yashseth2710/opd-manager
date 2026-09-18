"""A write is only reported as done once it has been kept.

The client used everywhere else waits for the whole application to finish,
teardown included, before it hands back a response, so it cannot see the
order these happen in. A browser can: it reads the answer as soon as it is
sent and asks for the record again straight away. If the commit is still
to come at that point, it gets the old record back, and a save that failed
to commit would already have been reported as a success.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Message, Receive, Scope, Send

from app.main import app
from tests.api.test_clinic import sign_up
from tests.api.test_doctors import details


async def test_a_save_is_committed_before_the_answer_goes_out(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sign_up(client)
    happened: list[str] = []

    commit = AsyncSession.commit

    async def noting_commit(self: AsyncSession) -> None:
        await commit(self)
        happened.append("committed")

    monkeypatch.setattr(AsyncSession, "commit", noting_commit)

    async def watched(scope: Scope, receive: Receive, send: Send) -> None:
        async def forward(message: Message) -> None:
            if message["type"] == "http.response.start":
                happened.append("answered")
            await send(message)

        await app(scope, receive, forward)

    async with AsyncClient(
        transport=ASGITransport(app=watched),
        base_url="https://testserver",
        cookies=client.cookies,
    ) as browser:
        response = await browser.post("/api/v1/doctors", json=details())

    assert response.status_code == 201, response.text
    assert happened.index("committed") < happened.index("answered"), happened
