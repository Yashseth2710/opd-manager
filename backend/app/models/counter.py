"""The per-clinic counters behind human-readable record numbers.

A patient number has to read as PT-000012, which means the clinic's twelfth
patient and nobody else's. A UUID cannot be read down a phone line, and a
count of existing rows races with itself the moment two receptionists
register someone at the same time.
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PATIENT = "patient"
INVOICE = "invoice"
PRESCRIPTION = "prescription"
LAB_ORDER = "lab_order"


class TenantCounter(Base):
    __tablename__ = "tenant_counters"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    counter: Mapped[str] = mapped_column(String(24), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
