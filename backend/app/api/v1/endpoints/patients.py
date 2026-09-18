"""Patient records.

Every route resolves the caller and is gated on a permission, and every read
goes through the scoped repository, so a record belonging to another clinic
is not found rather than forbidden.
"""

from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.models.patient import ACTIVE
from app.repositories.patients import AllergyRepository, Listed, PatientRepository, names_of
from app.schemas.patient import (
    AllergyOut,
    AllergyWrite,
    DuplicateCandidate,
    DuplicateCheck,
    PatientCreate,
    PatientOut,
    PatientPage,
    PatientSummary,
    PatientUpdate,
    Removed,
)
from app.services import patients as service

router = APIRouter(tags=["patients"])


def _summary(row: Listed) -> PatientSummary:
    patient = row.patient
    return PatientSummary(
        id=patient.id,
        patient_number=patient.patient_number,
        full_name=patient.full_name,
        preferred_name=patient.preferred_name,
        phone=patient.phone,
        date_of_birth=patient.date_of_birth,
        age=service.age_label(patient.date_of_birth),
        gender=patient.gender,
        blood_group=patient.blood_group,
        status=patient.status,
        allergy_count=row.allergy_count,
        created_at=patient.created_at,
    )


def _detail(
    row: Listed, allergies: list[AllergyOut], registered_by_name: str | None
) -> PatientOut:
    patient = row.patient
    return PatientOut(
        **_summary(row).model_dump(),
        first_name=patient.first_name,
        last_name=patient.last_name,
        alternate_phone=patient.alternate_phone,
        email=patient.email,
        address=patient.address,
        emergency_contact=patient.emergency_contact,
        notes=patient.notes,
        archived_at=patient.archived_at,
        registered_by_name=registered_by_name,
        allergies=allergies,
    )


async def _read(
    session: AsyncSession, organization_id: uuid.UUID, patient_id: uuid.UUID
) -> PatientOut:
    row = await service.fetch(session, organization_id=organization_id, patient_id=patient_id)
    allergies = await AllergyRepository(session, organization_id).for_patient(patient_id)

    registered_by = row.patient.registered_by_id
    names = await names_of(session, {registered_by} if registered_by else set())

    return _detail(
        row,
        [AllergyOut.model_validate(allergy) for allergy in allergies],
        names.get(registered_by) if registered_by else None,
    )


@router.get("/patients")
async def list_patients(
    session: DbSession,
    query: str = Query(default="", max_length=120, alias="q"),
    status: str = Query(default=ACTIVE, pattern="^(active|archived|all)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    _: Caller = Depends(requires("patient:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PatientPage:
    found, total = await PatientRepository(session, organization_id).search(
        query=query,
        status=None if status == "all" else status,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return PatientPage(
        items=[_summary(row) for row in found],
        total=total,
        page=page,
        per_page=per_page,
        # Carried so a client can offer a way forward without a second
        # request to discover whether there is one.
        pages=max(math.ceil(total / per_page), 1),
    )


@router.post("/patients/check-duplicates")
async def check_duplicates(
    session: DbSession,
    body: DuplicateCheck,
    _: Caller = Depends(requires("patient:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> list[DuplicateCandidate]:
    """Asked while the form is still being filled in, so whoever is at the
    desk sees the existing record in time to open it instead."""
    found = await PatientRepository(session, organization_id).possible_duplicates(
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        email=body.email,
        date_of_birth=body.date_of_birth,
        exclude_id=body.exclude_id,
    )
    return [
        DuplicateCandidate(
            **_summary(row).model_dump(),
            reason=service.candidate_reason(row.patient, phone=body.phone, email=body.email),
        )
        for row in found
    ]


@router.post("/patients", status_code=201)
async def register_patient(
    session: DbSession,
    body: PatientCreate,
    caller: Caller = Depends(requires("patient:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PatientOut:
    patient = await service.register(
        session, organization_id=organization_id, actor_id=caller.user_id, body=body
    )
    return _detail(Listed(patient=patient, allergy_count=0), [], None)


@router.get("/patients/{patient_id}")
async def read_patient(
    session: DbSession,
    patient_id: uuid.UUID,
    _: Caller = Depends(requires("patient:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PatientOut:
    return await _read(session, organization_id, patient_id)


@router.patch("/patients/{patient_id}")
async def update_patient(
    session: DbSession,
    patient_id: uuid.UUID,
    body: PatientUpdate,
    _: Caller = Depends(requires("patient:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PatientOut:
    await service.update(
        session, organization_id=organization_id, patient_id=patient_id, body=body
    )
    return await _read(session, organization_id, patient_id)


@router.post("/patients/{patient_id}/archive")
async def archive_patient(
    session: DbSession,
    patient_id: uuid.UUID,
    _: Caller = Depends(requires("patient:archive")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PatientOut:
    """Hides the record from the day-to-day lists. Nothing is deleted: the
    visits, invoices and notes that hang off it stay exactly as they were."""
    await service.set_archived(
        session, organization_id=organization_id, patient_id=patient_id, archived=True
    )
    return await _read(session, organization_id, patient_id)


@router.post("/patients/{patient_id}/restore")
async def restore_patient(
    session: DbSession,
    patient_id: uuid.UUID,
    _: Caller = Depends(requires("patient:archive")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PatientOut:
    await service.set_archived(
        session, organization_id=organization_id, patient_id=patient_id, archived=False
    )
    return await _read(session, organization_id, patient_id)


@router.post("/patients/{patient_id}/allergies", status_code=201)
async def record_allergy(
    session: DbSession,
    patient_id: uuid.UUID,
    body: AllergyWrite,
    caller: Caller = Depends(requires("patient:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AllergyOut:
    allergy = await service.add_allergy(
        session,
        organization_id=organization_id,
        patient_id=patient_id,
        actor_id=caller.user_id,
        body=body,
    )
    return AllergyOut.model_validate(allergy)


@router.delete("/patients/{patient_id}/allergies/{allergy_id}")
async def remove_allergy(
    session: DbSession,
    patient_id: uuid.UUID,
    allergy_id: uuid.UUID,
    _: Caller = Depends(requires("patient:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Removed:
    await service.remove_allergy(
        session,
        organization_id=organization_id,
        patient_id=patient_id,
        allergy_id=allergy_id,
    )
    return Removed()
