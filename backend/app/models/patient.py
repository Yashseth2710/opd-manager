"""Patient records.

The one table in the system a clinic would refuse to lose. Nothing here is
deleted: archiving hides a record from the day-to-day lists while leaving the
history that hangs off it intact.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantRow, TimestampMixin

ACTIVE = "active"
ARCHIVED = "archived"

GENDERS = ("female", "male", "other")
BLOOD_GROUPS = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")
SEVERITIES = ("mild", "moderate", "severe")

# Matched against the search box so a receptionist reading a number off a
# card finds the one record instead of every name that happens to contain it.
NUMBER_PREFIX = "PT"


class Patient(TimestampMixin, TenantRow):
    __tablename__ = "patients"
    __table_args__ = (
        Index("uq_patients_number", "organization_id", "patient_number", unique=True),
        Index("ix_patients_phone", "organization_id", "phone"),
        Index("ix_patients_status_name", "organization_id", "status", "last_name"),
        # Search tolerates the spelling a name was heard rather than read in.
        # Built on the same expression the query uses, or Postgres cannot use
        # it and every search becomes a sequential scan.
        Index(
            "ix_patients_name_trgm",
            text("lower(first_name || ' ' || last_name) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )

    patient_number: Mapped[str] = mapped_column(String(24), nullable=False)

    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    # What they are actually called, which is often not either of the above.
    preferred_name: Mapped[str | None] = mapped_column(String(80))

    phone: Mapped[str | None] = mapped_column(String(32))
    alternate_phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))

    # Age is derived from this on the way out. A stored age is wrong within
    # a year, and wrong in a way nobody notices until it matters.
    date_of_birth: Mapped[dt.date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(16))
    blood_group: Mapped[str | None] = mapped_column(String(8))

    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    emergency_contact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ACTIVE)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    registered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_archived(self) -> bool:
        return self.status == ARCHIVED


class PatientAllergy(TimestampMixin, TenantRow):
    """Carried on the patient rather than on a visit.

    An allergy is a standing fact about a person, and the moment it matters
    most is the moment nobody has time to read back through old notes.
    """

    __tablename__ = "patient_allergies"
    __table_args__ = (Index("ix_patient_allergies_patient", "organization_id", "patient_id"),)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
    )
    substance: Mapped[str] = mapped_column(String(120), nullable=False)
    reaction: Mapped[str | None] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="moderate")
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
