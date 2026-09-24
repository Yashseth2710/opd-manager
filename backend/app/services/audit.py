"""Reading back what the clinic has done."""

from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationFailed
from app.models import Organization
from app.repositories.audit import AuditRepository
from app.services.doctors import clinic_zone

# The log's filter reads in these terms, not in table names.
AREAS: dict[str, tuple[str, ...]] = {
    "patients": ("patient", "allergy", "document"),
    "appointments": ("appointment", "visit"),
    "clinical": ("consultation", "vitals", "lab_order", "prescription"),
    "billing": ("invoice", "payment_link"),
    "people": ("staff", "invitation", "doctor"),
    "clinic": ("clinic",),
    "sign_in": ("account",),
}


async def read(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    area: str | None,
    actor_id: uuid.UUID | None,
    resource_type: str | None,
    resource_id: uuid.UUID | None,
    first: dt.date | None,
    last: dt.date | None,
    typed: str | None,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    if first and last and last < first:
        raise ValidationFailed(
            {"to": "The last day comes before the first one."},
            "The last day comes before the first one.",
        )
    zone = clinic_zone(clinic)
    since = dt.datetime.combine(first, dt.time(), tzinfo=zone) if first else None
    until = (
        dt.datetime.combine(last + dt.timedelta(days=1), dt.time(), tzinfo=zone)
        if last
        else None
    )
    log = AuditRepository(session, organization_id)
    entries, total = await log.page(
        types=AREAS[area] if area else None,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        since=since,
        until=until,
        typed=typed,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return {
        "items": entries,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(math.ceil(total / per_page), 1),
        "actors": [{"id": actor, "name": name} for actor, name in await log.actors()],
    }
