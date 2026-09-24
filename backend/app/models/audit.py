"""The clinic's record of who did what, and when.

Written in the same transaction as the change it describes, so an entry
exists exactly when the change does. Nothing in the application updates or
deletes a row here, and the database refuses to as well: a trigger turns
away any UPDATE, and any DELETE except the one that comes from the clinic
itself being removed.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Connection, DateTime, Index, String, event, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow


class AuditEntry(TenantRow):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_created", "organization_id", text("created_at DESC")),
        Index("ix_audit_logs_org_resource", "organization_id", "resource_type", "resource_id"),
    )

    # No foreign key. The name beside it is what the log reads from, so the
    # entry stays whole whatever later becomes of the account.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_name: Mapped[str] = mapped_column(String(160), nullable=False)

    action: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    resource_label: Mapped[str | None] = mapped_column(String(200))

    # What moved, as {"field": [before, after]}, or a few facts worth
    # keeping about an action that is not a change of fields.
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# The migration carries the same two statements, so the suite's schema and
# the real one refuse the same things.
APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND NOT EXISTS (
        SELECT 1 FROM organizations WHERE id = OLD.organization_id
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'audit_logs is append-only';
END;
$$ LANGUAGE plpgsql
"""

APPEND_ONLY_TRIGGER = """
CREATE TRIGGER audit_logs_append_only
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()
"""


@event.listens_for(AuditEntry.__table__, "after_create")
def _append_only(_: object, connection: Connection, **__: object) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(text(APPEND_ONLY_FUNCTION))
    connection.execute(text(APPEND_ONLY_TRIGGER))
