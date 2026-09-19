"""Vital signs, taken for a place in the queue."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.core.exceptions import NotFound, ValidationFailed
from app.models import Organization
from app.schemas.vitals import Readings, Removed, VitalsOut, VitalsPage, VitalsTaken
from app.services import appointments
from app.services import vitals as service
from app.services.appointments import Reach

router = APIRouter(tags=["vitals"])


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    return clinic


async def _reach(session: AsyncSession, organization_id: uuid.UUID, caller: Caller) -> Reach:
    return await appointments.reach_of(
        session, organization_id=organization_id, user_id=caller.user_id, role=caller.role
    )


async def _answer(
    session: AsyncSession, organization_id: uuid.UUID, caller: Caller, vitals_id: uuid.UUID
) -> VitalsOut:
    found = await service.one(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=await _reach(session, organization_id, caller),
        may_record=caller.may("vitals:record"),
        vitals_id=vitals_id,
    )
    return VitalsOut.model_validate(found)


@router.get("/vitals")
async def list_vitals(
    session: DbSession,
    patient_id: uuid.UUID | None = Query(default=None),
    queue_entry_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    caller: Caller = Depends(requires("vitals:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> VitalsPage:
    """A patient's readings, newest first, or the one set taken for a visit."""
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    may_record = caller.may("vitals:record")
    if queue_entry_id is not None:
        found = await service.for_entry(
            session,
            organization_id=organization_id,
            clinic=clinic,
            reach=reach,
            may_record=may_record,
            entry_id=queue_entry_id,
        )
        return VitalsPage.model_validate(
            {"items": [found] if found else [], "total": 1 if found else 0}
        )
    if patient_id is None:
        raise ValidationFailed({"patient_id": "Say whose vital signs to show."})
    page = await service.for_patient(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        may_record=may_record,
        patient_id=patient_id,
        limit=limit,
        offset=offset,
    )
    return VitalsPage.model_validate(page)


@router.post("/vitals", status_code=201)
async def take_vitals(
    session: DbSession,
    body: VitalsTaken,
    caller: Caller = Depends(requires("vitals:record")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> VitalsOut:
    vitals_id = await service.take(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=await _reach(session, organization_id, caller),
        actor_id=caller.user_id,
        entry_id=body.queue_entry_id,
        readings=body,
    )
    return await _answer(session, organization_id, caller, vitals_id)


@router.get("/vitals/{vitals_id}")
async def read_vitals(
    session: DbSession,
    vitals_id: uuid.UUID,
    caller: Caller = Depends(requires("vitals:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> VitalsOut:
    return await _answer(session, organization_id, caller, vitals_id)


@router.put("/vitals/{vitals_id}")
async def correct_vitals(
    session: DbSession,
    vitals_id: uuid.UUID,
    body: Readings,
    caller: Caller = Depends(requires("vitals:record")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> VitalsOut:
    """Replaces the whole set. A reading left out is cleared."""
    await service.change(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=await _reach(session, organization_id, caller),
        actor_id=caller.user_id,
        vitals_id=vitals_id,
        readings=body,
    )
    return await _answer(session, organization_id, caller, vitals_id)


@router.delete("/vitals/{vitals_id}")
async def remove_vitals(
    session: DbSession,
    vitals_id: uuid.UUID,
    caller: Caller = Depends(requires("vitals:record")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Removed:
    """For a set taken for the wrong person, on the day only."""
    await service.remove(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=await _reach(session, organization_id, caller),
        vitals_id=vitals_id,
    )
    return Removed()
