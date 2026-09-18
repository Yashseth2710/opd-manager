"""Consultation notes.

Opened from a place in the queue by the doctor in the room, saved as they
write, finished once, and added to afterwards only by addendum.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.core.exceptions import NotFound
from app.models import Organization
from app.schemas.consultation import (
    AddendumWrite,
    ConsultationDetail,
    ConsultationFinish,
    ConsultationOpen,
    ConsultationPage,
    ConsultationWrite,
)
from app.services import appointments
from app.services import consultations as service

router = APIRouter(tags=["consultations"])


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    return clinic


async def _reach(
    session: AsyncSession, organization_id: uuid.UUID, caller: Caller
) -> appointments.Reach:
    return await appointments.reach_of(
        session, organization_id=organization_id, user_id=caller.user_id, role=caller.role
    )


async def _detail(
    session: AsyncSession,
    organization_id: uuid.UUID,
    caller: Caller,
    reach: appointments.Reach,
    consultation_id: uuid.UUID,
) -> ConsultationDetail:
    found = await service.detail(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=reach,
        can_write=caller.may("consultation:update"),
        consultation_id=consultation_id,
    )
    return ConsultationDetail.model_validate(found)


@router.get("/consultations")
async def list_consultations(
    session: DbSession,
    patient_id: uuid.UUID | None = Query(default=None),
    doctor_id: uuid.UUID | None = Query(default=None),
    status: Literal["draft", "completed"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    caller: Caller = Depends(requires("consultation:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ConsultationPage:
    found = await service.listed(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=await _reach(session, organization_id, caller),
        doctor_id=doctor_id,
        patient_id=patient_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ConsultationPage.model_validate(found)


@router.post("/consultations", status_code=201)
async def open_consultation(
    session: DbSession,
    body: ConsultationOpen,
    response: Response,
    caller: Caller = Depends(requires("consultation:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ConsultationDetail:
    """The notes for a patient in the room. Asking twice hands back the same
    notes, answered 200 rather than 201."""
    reach = await _reach(session, organization_id, caller)
    consultation, made = await service.open_for(
        session,
        organization_id=organization_id,
        reach=reach,
        actor_id=caller.user_id,
        entry_id=body.queue_entry_id,
    )
    if not made:
        response.status_code = 200
    return await _detail(session, organization_id, caller, reach, consultation.id)


@router.get("/consultations/{consultation_id}")
async def read_consultation(
    session: DbSession,
    consultation_id: uuid.UUID,
    caller: Caller = Depends(requires("consultation:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ConsultationDetail:
    reach = await _reach(session, organization_id, caller)
    return await _detail(session, organization_id, caller, reach, consultation_id)


@router.patch("/consultations/{consultation_id}")
async def save_consultation(
    session: DbSession,
    consultation_id: uuid.UUID,
    body: ConsultationWrite,
    caller: Caller = Depends(requires("consultation:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ConsultationDetail:
    reach = await _reach(session, organization_id, caller)
    await service.save(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=reach,
        consultation_id=consultation_id,
        body=body,
    )
    return await _detail(session, organization_id, caller, reach, consultation_id)


@router.post("/consultations/{consultation_id}/complete")
async def finish_consultation(
    session: DbSession,
    consultation_id: uuid.UUID,
    body: ConsultationFinish,
    caller: Caller = Depends(requires("consultation:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ConsultationDetail:
    reach = await _reach(session, organization_id, caller)
    await service.finish(
        session,
        organization_id=organization_id,
        reach=reach,
        actor_id=caller.user_id,
        consultation_id=consultation_id,
        version=body.version,
    )
    return await _detail(session, organization_id, caller, reach, consultation_id)


@router.post("/consultations/{consultation_id}/addenda", status_code=201)
async def add_addendum(
    session: DbSession,
    consultation_id: uuid.UUID,
    body: AddendumWrite,
    caller: Caller = Depends(requires("consultation:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> ConsultationDetail:
    reach = await _reach(session, organization_id, caller)
    await service.add_addendum(
        session,
        organization_id=organization_id,
        reach=reach,
        actor_id=caller.user_id,
        consultation_id=consultation_id,
        body=body.body,
    )
    return await _detail(session, organization_id, caller, reach, consultation_id)
