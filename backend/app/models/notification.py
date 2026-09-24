"""What somebody at the clinic should hear about, and how they want to hear it.

A notice is always kept in the app. Whether it is also emailed is each
person's own choice, made per kind, and the email goes out only once the
change it is about has been saved.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

APPOINTMENT_BOOKED = "appointment_booked"
APPOINTMENT_MOVED = "appointment_moved"
APPOINTMENT_CANCELLED = "appointment_cancelled"
LAB_RESULT = "lab_result"
PAID_ONLINE = "paid_online"
BILL_VOIDED = "bill_voided"
STAFF_JOINED = "staff_joined"
ROLE_CHANGED = "role_changed"
ACCOUNT_LOCKED = "account_locked"

KINDS = (
    APPOINTMENT_BOOKED,
    APPOINTMENT_MOVED,
    APPOINTMENT_CANCELLED,
    LAB_RESULT,
    PAID_ONLINE,
    BILL_VOIDED,
    STAFF_JOINED,
    ROLE_CHANGED,
    ACCOUNT_LOCKED,
)

IN_APP = "in_app"
EMAIL = "email"


class Notification(TenantRow):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", text("created_at DESC")),
        Index(
            "ix_notifications_user_unread",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str | None] = mapped_column(String(400))
    # A path inside the app, never an address somewhere else.
    link: Mapped[str | None] = mapped_column(String(300))
    # The channels it went out on beyond the app. Email only, for now.
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default=IN_APP)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotificationPreference(TimestampMixin, TenantRow):
    """Only the kinds somebody has changed from the default have a row."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_notification_preference_kind"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False)
