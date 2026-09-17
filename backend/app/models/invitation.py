"""Invitations to join an existing clinic.

This is the only way to get an account at a clinic somebody else created.
Registering always makes a new clinic, so without this a receptionist who
signed up on her own would end up administering an empty one.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

PENDING = "pending"
ACCEPTED = "accepted"
REVOKED = "revoked"

EXPIRY_DAYS = 7


class Invitation(TimestampMixin, TenantRow):
    __tablename__ = "invitations"
    __table_args__ = (
        # One live invitation per address per clinic. The same person can
        # still be invited to two clinics, which is the point of email being
        # unique per clinic rather than globally.
        Index(
            "uq_invitations_pending_email",
            "organization_id",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    # Carried on the row rather than held in memory: nothing survives between
    # requests in a serverless function, and the account created on acceptance
    # would otherwise start with no name.
    first_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Kept so the audit trail survives the inviter leaving.
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    invited_by_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")

    # Only the hash. A dump of this table cannot be used to join a clinic.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PENDING)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_open(self) -> bool:
        return (
            self.status == PENDING
            and self.expires_at > dt.datetime.now(dt.UTC)
            and self.accepted_at is None
        )
