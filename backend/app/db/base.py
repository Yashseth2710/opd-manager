"""Declarative base and the columns every table carries."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Connection, DateTime, ForeignKey, MetaData, event, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from uuid6 import uuid7


class Base(DeclarativeBase):
    pass


# The schema leans on two extensions: pg_trgm for the trigram index behind
# patient search, btree_gist for the constraint that stops a doctor being
# booked twice for one slot. Migrations create them, and so must a metadata
# build, which is how the suite raises its schema.
EXTENSIONS = ("pg_trgm", "btree_gist")


@event.listens_for(Base.metadata, "before_create")
def _create_extensions(_: MetaData, connection: Connection, **__: object) -> None:
    if connection.dialect.name != "postgresql":
        return
    for extension in EXTENSIONS:
        connection.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UUIDMixin:
    # UUIDv7 sorts by creation time, so primary keys stay sequential enough
    # for a b-tree to stay compact while remaining unguessable.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


class TenantRow(UUIDMixin, Base):
    """Base for every table that holds one clinic's data.

    Declaring the column here rather than in a loose mixin is what lets the
    scoped repository be typed: anything it accepts provably carries an
    organisation, so a query cannot silently be written against a table that
    has none.
    """

    __abstract__ = True

    @declared_attr
    @classmethod
    def organization_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
