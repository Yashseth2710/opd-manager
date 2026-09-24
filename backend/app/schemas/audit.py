"""The audit log as the clinic admin reads it."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Area = Literal["patients", "appointments", "clinical", "billing", "people", "clinic", "sign_in"]


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: dt.datetime
    actor_id: uuid.UUID | None
    actor_name: str
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    resource_label: str | None
    changes: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None


class ActorOut(BaseModel):
    id: uuid.UUID
    name: str


class AuditPage(BaseModel):
    items: list[AuditEntryOut]
    total: int
    page: int
    per_page: int
    pages: int
    actors: list[ActorOut]
