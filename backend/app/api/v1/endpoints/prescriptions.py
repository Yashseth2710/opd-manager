"""Prescriptions once issued, and the medicines a doctor picks them from.

Drafts are written through the notes and never appear here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.core.exceptions import NotFound
from app.models import Organization
from app.schemas.prescription import (
    Correction,
    MedicineSuggestion,
    PrescriptionDetail,
    PrescriptionPage,
)
from app.services import appointments
from app.services import prescriptions as service
from app.services.doctors import clinic_zone
from app.services.prescription_pdf import render

router = APIRouter(tags=["prescriptions"])


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    return clinic


async def _detail(
    session: AsyncSession,
    organization_id: uuid.UUID,
    caller: Caller,
    prescription_id: uuid.UUID,
) -> PrescriptionDetail:
    reach = await appointments.reach_of(
        session, organization_id=organization_id, user_id=caller.user_id, role=caller.role
    )
    found = await service.detail(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=reach,
        may_correct=caller.may("prescription:create"),
        prescription_id=prescription_id,
    )
    return PrescriptionDetail.model_validate(found)


@router.get("/medicines")
async def suggest_medicines(
    session: DbSession,
    q: str = Query(min_length=2, max_length=60),
    limit: int = Query(default=12, ge=1, le=20),
    caller: Caller = Depends(requires("prescription:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> list[MedicineSuggestion]:
    """What this clinic has prescribed before, then the published list."""
    found = await service.suggest(
        session, organization_id=organization_id, typed=q.strip(), limit=limit
    )
    return [MedicineSuggestion.model_validate(each) for each in found]


@router.get("/prescriptions")
async def list_prescriptions(
    session: DbSession,
    patient_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    caller: Caller = Depends(requires("prescription:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PrescriptionPage:
    found = await service.listed(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        patient_id=patient_id,
        limit=limit,
        offset=offset,
    )
    return PrescriptionPage.model_validate(found)


@router.get("/prescriptions/{prescription_id}")
async def read_prescription(
    session: DbSession,
    prescription_id: uuid.UUID,
    caller: Caller = Depends(requires("prescription:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PrescriptionDetail:
    return await _detail(session, organization_id, caller, prescription_id)


@router.get("/prescriptions/{prescription_id}/pdf")
async def prescription_pdf(
    session: DbSession,
    prescription_id: uuid.UUID,
    caller: Caller = Depends(requires("prescription:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Response:
    """The page to print or send. Made fresh each time: an issued
    prescription never changes, so every copy comes out the same."""
    found = await _detail(session, organization_id, caller, prescription_id)
    clinic = await _clinic(session, organization_id)
    issued = found.issued_at.astimezone(clinic_zone(clinic)) if found.issued_at else None
    content = render(found.model_dump(), issued_local=issued)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{found.number or "prescription"}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/prescriptions/{prescription_id}/corrections", status_code=201)
async def correct_prescription(
    session: DbSession,
    prescription_id: uuid.UUID,
    body: Correction,
    caller: Caller = Depends(requires("prescription:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PrescriptionDetail:
    """Issues a new prescription in place of this one, which stays on record
    marked as replaced."""
    reach = await appointments.reach_of(
        session, organization_id=organization_id, user_id=caller.user_id, role=caller.role
    )
    replacement = await service.correct(
        session,
        organization_id=organization_id,
        reach=reach,
        actor_id=caller.user_id,
        prescription_id=prescription_id,
        lines=body.medicines,
        instructions=body.instructions,
        reason=body.reason,
    )
    return await _detail(session, organization_id, caller, replacement.id)
