"""Test fixtures.

The suite runs against a real Postgres because the things worth testing here
are the ones an in-memory stand-in gets wrong: a functional unique index, a
cascade, the exact behaviour of a case-insensitive lookup.

Redis is replaced with an in-process double so the suite does not need a
network service, and so a test can move time forward without waiting.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Loaded before anything reads configuration, so the suite picks up its own
# disposable database rather than whatever is being worked against. Absent on
# CI, where the same values arrive as environment variables.
load_dotenv(Path(__file__).resolve().parents[1] / ".env.test", override=True)

from app.core import email as email_module  # noqa: E402
from app.core import redis as redis_module  # noqa: E402
from app.core import storage as storage_module  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import app  # noqa: E402


class FakeRedis:
    """Enough of Redis for the sign-in paths, with expiry that honours a
    clock the tests control."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.expiry: dict[str, float] = {}
        self.offset = 0.0

    def _now(self) -> float:
        return time.monotonic() + self.offset

    def advance(self, seconds: float) -> None:
        self.offset += seconds

    def _sweep(self, key: str) -> None:
        deadline = self.expiry.get(key)
        if deadline is not None and deadline <= self._now():
            self.values.pop(key, None)
            self.sets.pop(key, None)
            self.expiry.pop(key, None)

    async def command(self, *args: Any) -> Any:
        name = str(args[0]).upper()
        key = str(args[1]) if len(args) > 1 else ""
        self._sweep(key)

        if name == "SET":
            self.values[key] = str(args[2])
            if len(args) >= 5 and str(args[3]).upper() == "EX":
                self.expiry[key] = self._now() + float(args[4])
            return "OK"
        if name == "GET":
            return self.values.get(key)
        if name == "GETDEL":
            self.expiry.pop(key, None)
            return self.values.pop(key, None)
        if name == "DEL":
            removed = 0
            for target in args[1:]:
                target = str(target)
                removed += int(self.values.pop(target, None) is not None)
                removed += int(self.sets.pop(target, None) is not None)
                self.expiry.pop(target, None)
            return removed
        if name == "INCR":
            current = int(self.values.get(key, "0")) + 1
            self.values[key] = str(current)
            return current
        if name == "EXPIRE":
            self.expiry[key] = self._now() + float(args[2])
            return 1
        if name == "TTL":
            deadline = self.expiry.get(key)
            if deadline is None:
                return -1 if key in self.values else -2
            return max(int(deadline - self._now()), 0)
        if name == "SADD":
            self.sets.setdefault(key, set()).add(str(args[2]))
            return 1
        if name == "SREM":
            self.sets.get(key, set()).discard(str(args[2]))
            return 1
        if name == "SMEMBERS":
            return sorted(self.sets.get(key, set()))
        raise AssertionError(f"FakeRedis has no {name}")


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRedis]:
    double = FakeRedis()
    monkeypatch.setattr(redis_module, "command", double.command)
    yield double


class Outbox:
    """Records what the application asked to send.

    Reading the link from here is how a test follows the journey a person
    follows from their inbox. The token cannot be read back out of storage:
    only its hash is kept.
    """

    def __init__(self) -> None:
        self.messages: list[email_module.Message] = []

    async def send(self, message: email_module.Message) -> email_module.Delivery:
        self.messages.append(message)
        return email_module.Delivery(sent=True, provider="outbox")

    def latest_token(self) -> str:
        assert self.messages, "nothing was sent"
        return self.messages[-1].action_url.split("token=")[1]

    @property
    def recipients(self) -> list[str]:
        return [message.to for message in self.messages]


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[Outbox]:
    box = Outbox()
    monkeypatch.setattr(email_module, "send", box.send)
    yield box


class FakeStore:
    """Files kept in memory, with a switch to make the store refuse, so a
    test can see what the application does when the real one is down."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.down = False
        self.puts = 0

    def _check(self) -> None:
        if self.down:
            raise storage_module.StorageUnavailable

    async def put(self, pathname: str, content: bytes, content_type: str) -> str:
        self._check()
        self.puts += 1
        url = f"https://store.test/{pathname}"
        self.files[url] = content
        return url

    async def read(self, url: str) -> bytes:
        self._check()
        if url not in self.files:
            raise storage_module.Missing
        return self.files[url]

    async def delete(self, url: str) -> None:
        self._check()
        self.files.pop(url, None)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeStore]:
    double = FakeStore()
    monkeypatch.setattr(storage_module, "put", double.put)
    monkeypatch.setattr(storage_module, "read", double.read)
    monkeypatch.setattr(storage_module, "delete", double.delete)
    yield double


def _refuse_to_run_against_anything_real() -> None:
    """The schema fixture drops every table. That is fine against a database
    kept for the suite and catastrophic anywhere else, so the suite will not
    start unless the environment says plainly that this one is disposable."""
    settings = get_settings()
    if settings.environment != "test":
        raise RuntimeError(
            "Tests drop every table. Set ENVIRONMENT=test and point "
            "DATABASE_URL at a database kept for the suite."
        )
    if "-pooler." in settings.database_url:
        raise RuntimeError("Point the suite at the direct endpoint, not the pooler.")
    if settings.email_configured:
        # Otherwise the suite inherits whatever provider the developer has
        # set up, registration starts demanding confirmation, and a dozen
        # unrelated tests fail in ways that point nowhere near the cause.
        raise RuntimeError(
            "Blank BREVO_API_KEY and RESEND_API_KEY for the suite. Tests that "
            "need a provider configured say so for themselves."
        )
    if settings.blob_read_write_token:
        raise RuntimeError(
            "Blank BLOB_READ_WRITE_TOKEN for the suite, or it uploads to a real store."
        )
    if settings.online_payments:
        # Even test keys open real orders on a real account. The tests that
        # need a gateway stand one up for themselves.
        raise RuntimeError("Blank RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET for the suite.")


@pytest_asyncio.fixture(scope="session")
async def database() -> AsyncIterator[None]:
    """Builds the schema once. Rebuilding it per test means a round trip for
    every table on every test, which is slow anywhere and painful against a
    database in another region."""
    _refuse_to_run_against_anything_real()
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


_TABLES = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))


@pytest_asyncio.fixture
async def schema(database: None) -> AsyncIterator[None]:
    """Empties every table between tests.

    One statement rather than a drop and rebuild, and RESTART IDENTITY so a
    test never inherits a sequence position from the one before it.
    """
    async with get_engine().begin() as connection:
        await connection.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture
async def client(
    schema: None, fake_redis: FakeRedis, outbox: Outbox
) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    # https, because session cookies are marked Secure outside development
    # and a client speaking plain http would silently never send them back.
    async with AsyncClient(transport=transport, base_url="https://testserver") as http:
        yield http


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    from app.db.session import get_factory

    async with get_factory()() as db:
        yield db


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@sunrisecare.org"


GOOD_PASSWORD = "a properly long password"  # pragma: allowlist secret


def registration(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "clinic_name": "Sunrise Family Clinic",
        "first_name": "Priya",
        "last_name": "Nair",
        "email": unique_email("priya"),
        "password": GOOD_PASSWORD,
    }
    body.update(overrides)
    return body
