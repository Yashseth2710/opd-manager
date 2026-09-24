"""Notices, and each person's choice of which of them to get by email."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    link: str | None
    channel: str
    read_at: dt.datetime | None
    sent_at: dt.datetime | None
    created_at: dt.datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int
    # Whether older notices are there to ask for.
    more: bool


class Unread(BaseModel):
    unread: int


class PreferenceOut(BaseModel):
    kind: str
    label: str
    description: str
    email: bool


class Preferences(BaseModel):
    # False when no mail provider is set up, so the choice is shown but
    # cannot be made to mean anything yet.
    email_available: bool
    kinds: list[PreferenceOut]


class PreferenceIn(BaseModel):
    kind: str = Field(max_length=32)
    email: bool
