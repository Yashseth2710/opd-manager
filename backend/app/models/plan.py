"""Plans, and which one each clinic is on.

A plan is a set of limits kept as data, so changing what a plan allows is an
edit to a row rather than to the code. Plans belong to the platform and carry
no organisation.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

# The measures a plan can cap. A missing or null limit means no cap.
LIMITS = (
    "max_doctors",
    "max_staff",
    "max_patients",
    "max_appointments_per_month",
    "max_storage_mb",
)


class SubscriptionPlan(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "subscription_plans"

    slug: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # What the plan would cost a clinic each month. Shown, never charged.
    price_monthly: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    limits: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def limit(self, name: str) -> int | None:
        value = (self.limits or {}).get(name)
        return int(value) if value is not None else None


class OrganizationSubscription(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "organization_subscriptions"

    # One row per clinic. A clinic without one is treated as being on the
    # plan a new clinic falls back to.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Set while the clinic is trying a plan out. Once it passes, the clinic
    # is on the fallback plan until somebody chooses one for it.
    trial_ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
