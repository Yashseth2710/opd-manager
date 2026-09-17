"""Which provider sends, and what the application admits when none can."""

from __future__ import annotations

import httpx
import pytest

from app.core import email as mail
from app.core.config import Settings


def _with(monkeypatch: pytest.MonkeyPatch, **values: str) -> Settings:
    settings = Settings(**values)  # type: ignore[arg-type]
    monkeypatch.setattr(mail, "get_settings", lambda: settings)
    return settings


def test_no_provider_falls_back_to_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _with(monkeypatch, brevo_api_key="", resend_api_key="")
    assert mail.sender().name == "console"
    assert settings.email_configured is False


def test_brevo_is_used_when_its_key_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # pragma: allowlist secret
    settings = _with(monkeypatch, brevo_api_key="k", resend_api_key="")
    assert mail.sender().name == "brevo"
    assert settings.email_configured is True


def test_resend_is_used_on_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    # pragma: allowlist secret
    _with(monkeypatch, brevo_api_key="", resend_api_key="k")
    assert mail.sender().name == "resend"


def test_brevo_wins_when_both_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """An installation only carries two providers while moving between them."""
    # pragma: allowlist secret
    _with(monkeypatch, brevo_api_key="k", resend_api_key="j")
    assert mail.sender().name == "brevo"


async def test_the_console_never_claims_a_delivery() -> None:
    message = mail.reset_message(to="someone@example.com", name="Someone", url="http://x/y")
    assert (await mail.ConsoleSender().send(message)).sent is False


async def test_the_console_writes_the_link_and_nothing_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    link = "http://localhost:3000/reset-password?token=abc123"
    message = mail.reset_message(to="someone@example.com", name="Someone", url=link)
    with caplog.at_level("WARNING", logger="opd.email"):
        await mail.ConsoleSender().send(message)
    assert link in caplog.text


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("OPD Manager <hello@clinic.com>", ("OPD Manager", "hello@clinic.com")),
        ("hello@clinic.com", ("OPD Manager", "hello@clinic.com")),
        ("  Sunrise OPD <a@b.co>  ", ("Sunrise OPD", "a@b.co")),
    ],
)
def test_the_sender_splits_into_the_fields_providers_ask_for(
    configured: str, expected: tuple[str, str]
) -> None:
    assert Settings(mail_from=configured).mail_sender == expected


def test_the_rendered_message_carries_the_link_and_no_markup_break() -> None:
    link = "http://localhost:3000/verify-email?token=xyz"
    html = mail.render(mail.verification_message(to="a@b.co", name="Asha", url=link))
    assert html.count(link) == 2  # the button and the fallback line
    assert html.strip().endswith("</html>")


class _Recorder:
    """Stands in for the HTTP client so the request can be inspected without
    a key, an account, or a message going anywhere."""

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.url: str | None = None
        self.headers: dict[str, str] = {}
        self.payload: dict[str, object] = {}

    async def __aenter__(self) -> _Recorder:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(
        self, url: str, headers: dict[str, str], json: dict[str, object]
    ) -> _Recorder:
        self.url, self.headers, self.payload = url, headers, json
        return self

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise httpx.HTTPStatusError("refused", request=None, response=None)  # type: ignore[arg-type]


async def test_brevo_is_asked_in_the_shape_it_expects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with(
        monkeypatch,
        brevo_api_key="test-key-not-real",  # pragma: allowlist secret
        mail_from="Sunrise OPD <clinic@example.com>",
    )
    recorder = _Recorder()
    monkeypatch.setattr(mail.httpx, "AsyncClient", lambda **_: recorder)

    link = "http://localhost:3000/reset-password?token=abc"
    delivery = await mail.BrevoSender().send(
        mail.reset_message(to="priya@example.com", name="Priya", url=link)
    )

    assert delivery.sent is True
    assert recorder.url == "https://api.brevo.com/v3/smtp/email"
    assert recorder.headers["api-key"] == "test-key-not-real"  # pragma: allowlist secret
    assert recorder.payload["sender"] == {"name": "Sunrise OPD", "email": "clinic@example.com"}
    # Addressed to the account holder, never to anything the request named.
    assert recorder.payload["to"] == [{"email": "priya@example.com"}]
    assert link in str(recorder.payload["htmlContent"])


async def test_a_refused_message_is_reported_as_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider outage must not look like a successful delivery."""
    _with(monkeypatch, brevo_api_key="test-key-not-real")  # pragma: allowlist secret
    monkeypatch.setattr(mail.httpx, "AsyncClient", lambda **_: _Recorder(status=401))

    delivery = await mail.BrevoSender().send(
        mail.reset_message(to="priya@example.com", name="Priya", url="http://x/y")
    )
    assert delivery.sent is False


async def test_a_refusal_never_logs_the_link_or_the_address(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _with(monkeypatch, brevo_api_key="test-key-not-real")  # pragma: allowlist secret
    monkeypatch.setattr(mail.httpx, "AsyncClient", lambda **_: _Recorder(status=500))

    with caplog.at_level("ERROR", logger="opd.email"):
        await mail.BrevoSender().send(
            mail.reset_message(
                to="priya@example.com", name="Priya", url="http://x/?token=secretvalue"
            )
        )
    assert "priya@example.com" not in caplog.text
    assert "secretvalue" not in caplog.text


@pytest.mark.parametrize("password", ["1234567", "seven77"])
def test_a_password_under_the_minimum_is_refused(password: str) -> None:
    from app.core.security import MIN_PASSWORD_LENGTH, password_problem

    assert password_problem(password) == f"Use at least {MIN_PASSWORD_LENGTH} characters."


@pytest.mark.parametrize("password", ["12345678", "welcome1", "qwerty123", "password"])
def test_the_common_list_covers_the_lengths_the_minimum_now_allows(password: str) -> None:
    """Lowering the floor to eight puts these within reach, so the list has
    to reach down there too."""
    from app.core.security import password_problem

    assert password_problem(password) == (
        "That password is too widely used. Pick something else."
    )


def test_an_ordinary_eight_character_password_is_accepted() -> None:
    from app.core.security import password_problem

    assert password_problem("opdclinic") is None
