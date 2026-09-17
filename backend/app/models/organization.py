"""The clinic. Every other tenant table hangs off this one."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

# What a clinic runs on before anyone changes anything. Kept here rather than
# written into the row at creation, so raising a default reaches clinics that
# were made before it changed.
DEFAULT_SETTINGS: dict[str, Any] = {
    "consultation_duration_minutes": 15,
    "invoice_prefix": "INV",
    "token_prefix": "T",
    "tax_percent": "0.00",
    "consultation_fee": "0.00",
    "follow_up_fee": "0.00",
    "follow_up_window_days": 7,
}


class Organization(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text)

    # Free-form because an address is not the same shape in two countries,
    # and nothing queries inside it.
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    # Pending until the clinic finishes setup. Suspended is a platform action.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    onboarding_completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    # Settings that grow over time live here rather than becoming columns.
    # Anything that needs querying or constraining gets promoted to one.
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )

    @property
    def effective_settings(self) -> dict[str, Any]:
        """Stored values over defaults, so a key added later is not missing
        from every clinic created before it existed."""
        return {**DEFAULT_SETTINGS, **(self.settings or {})}

    @property
    def is_set_up(self) -> bool:
        return self.onboarding_completed_at is not None
