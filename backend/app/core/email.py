"""Outgoing email.

Delivery sits behind one interface so the rest of the application never knows
which provider is in use, or whether there is one at all. With no provider
configured the console sender writes the link to the log and reports honestly
that nothing was delivered, rather than pretending a message went out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger("opd.email")


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    heading: str
    body: str
    action_label: str
    action_url: str


@dataclass(frozen=True)
class Delivery:
    sent: bool
    provider: str


class Sender(Protocol):
    async def send(self, message: Message) -> Delivery: ...


# Inlined because email clients discard <style> blocks and external sheets.
_BODY = (
    "margin:0;padding:24px;background:#f7f9fa;"
    "font-family:-apple-system,Segoe UI,sans-serif;color:#0e2135"
)
_CARD = "max-width:520px;background:#ffffff;border:1px solid #dde4ea;border-radius:10px"
_BRAND = "margin:0 0 20px;font-size:15px;font-weight:600;letter-spacing:-0.01em"
_HEADING = "margin:0 0 12px;font-size:20px;line-height:1.3"
_TEXT = "margin:0 0 24px;font-size:15px;line-height:1.55;color:#4e5a66"
_BUTTON = (
    "display:inline-block;padding:11px 20px;background:#1f3450;color:#ffffff;"
    "text-decoration:none;border-radius:6px;font-size:15px;font-weight:500"
)
_FINE = "margin:0;font-size:13px;line-height:1.5;color:#6b7a87"


def render(message: Message) -> str:
    return f"""<!doctype html>
<html lang="en">
  <body style="{_BODY}">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td align="center">
        <table role="presentation" width="100%" style="{_CARD}">
          <tr><td style="padding:28px 28px 8px">
            <p style="{_BRAND}">OPD Manager</p>
            <h1 style="{_HEADING}">{message.heading}</h1>
            <p style="{_TEXT}">{message.body}</p>
            <a href="{message.action_url}" style="{_BUTTON}">{message.action_label}</a>
          </td></tr>
          <tr><td style="padding:20px 28px 28px">
            <p style="{_FINE}">
              If the button does not work, paste this into your browser:<br>
              <span style="word-break:break-all;color:#456080">{message.action_url}</span>
            </p>
            <p style="{_FINE};margin-top:16px">
              If you were not expecting this, you can ignore it.
            </p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""


class ConsoleSender:
    """Development and demo. The link goes to the server log and nowhere else.

    It is deliberately not returned to the caller: a reset response that
    carried the link would tell anyone which addresses have accounts.
    """

    name = "console"

    async def send(self, message: Message) -> Delivery:
        logger.warning(
            "email not sent, no provider configured\n"
            "  to:      %s\n"
            "  subject: %s\n"
            "  link:    %s",
            message.to,
            message.subject,
            message.action_url,
        )
        return Delivery(sent=False, provider=self.name)


class ResendSender:
    """Delivers anywhere, once a sending domain has been verified.

    Until then the provider only accepts the account holder's own address and
    drops everything else upstream. That is a provider setting, not something
    this code can work around.
    """

    name = "resend"

    async def send(self, message: Message) -> Delivery:
        settings = get_settings()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json={
                        "from": settings.mail_from,
                        "to": [message.to],
                        "subject": message.subject,
                        "html": render(message),
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError:
            # Never the address and never the link, either of which would put
            # a working credential in the log.
            logger.error("email provider rejected a message: %s", message.subject)
            return Delivery(sent=False, provider=self.name)
        return Delivery(sent=True, provider=self.name)


class BrevoSender:
    """Delivers anywhere once a single sender address has been confirmed.

    Verifying one address rather than a whole domain is why this is here: it
    means reset links reach real recipients without owning a domain.
    """

    name = "brevo"

    async def send(self, message: Message) -> Delivery:
        settings = get_settings()
        name, address = settings.mail_sender
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                response = await client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={
                        "api-key": settings.brevo_api_key,
                        "accept": "application/json",
                    },
                    json={
                        "sender": {"name": name, "email": address},
                        "to": [{"email": message.to}],
                        "subject": message.subject,
                        "htmlContent": render(message),
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError:
            # Never the address and never the link: one identifies a person,
            # the other is a working credential.
            logger.error("email provider rejected a message: %s", message.subject)
            return Delivery(sent=False, provider=self.name)
        return Delivery(sent=True, provider=self.name)


def sender() -> Sender:
    """Whichever provider is configured, or the console when none is.

    Brevo wins when both are set, because an installation only bothers with
    a second provider while it is moving to one.
    """
    settings = get_settings()
    if settings.brevo_api_key:
        return BrevoSender()
    if settings.resend_api_key:
        return ResendSender()
    return ConsoleSender()


async def send(message: Message) -> Delivery:
    return await sender().send(message)


def verification_message(*, to: str, name: str, url: str) -> Message:
    return Message(
        to=to,
        subject="Confirm your email address",
        heading=f"Welcome, {name}",
        body=(
            "Confirm this address to finish setting up your clinic. "
            "The link works once and expires in 30 minutes."
        ),
        action_label="Confirm email",
        action_url=url,
    )


def reset_message(*, to: str, name: str, url: str) -> Message:
    return Message(
        to=to,
        subject="Reset your password",
        heading=f"Hello, {name}",
        body=(
            "Someone asked to reset the password on this account. "
            "The link works once and expires in 30 minutes. "
            "Your current password stays active until you choose a new one."
        ),
        action_label="Choose a new password",
        action_url=url,
    )


def payment_link_message(
    *, to: str, name: str, clinic: str, amount: str, number: str, until: str, url: str
) -> Message:
    greeting = f"Hello, {name}" if name else "Hello"
    return Message(
        to=to,
        subject=f"Your bill from {clinic}, {amount}",
        heading=greeting,
        body=(
            f"{clinic} has sent you bill {number} for {amount}. "
            f"You can pay it by UPI or card from this link until {until}. "
            "If you have already paid at the clinic, nothing more is owed and "
            "the link will say so."
        ),
        action_label=f"Pay {amount}",
        action_url=url,
    )


def invitation_message(
    *, to: str, name: str, clinic: str, role: str, inviter: str, url: str
) -> Message:
    greeting = f"Hello, {name}" if name else "Hello"
    return Message(
        to=to,
        subject=f"{inviter} has added you to {clinic}",
        heading=greeting,
        body=(
            f"{inviter} has set up an account for you at {clinic}, "
            f"as {role.lower()}. Choose a password and you are in. "
            "The link expires in seven days."
        ),
        action_label="Set your password",
        action_url=url,
    )
