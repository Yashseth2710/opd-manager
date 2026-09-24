"""Doctors, their weekly hours, and who is free when.

Reading is open to everyone who books, checks in or bills; changing a
profile or a rota is not. Every read goes through the scoped repository, so
another clinic's doctor is not found rather than forbidden.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, Trail, current_tenant, requires
from app.models import Organization
from app.models.doctor import ACTIVE
from app.repositories.doctors import (
    DoctorRepository,
    LeaveRepository,
    Listed,
    ScheduleRepository,
    names_of,
)
from app.schemas.doctor import (
    Availability,
    DoctorCreate,
    DoctorOut,
    DoctorPage,
    DoctorSummary,
    DoctorUpdate,
    LeaveOut,
    LeaveWrite,
    Removed,
    ScheduleBlockOut,
    ScheduleWrite,
)
from app.services import doctors as service
from app.services import events

router = APIRouter(tags=["doctors"])

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise service.DoctorNotFound
    return clinic


def _summary(row: Listed, clinic: Organization) -> DoctorSummary:
    doctor = row.doctor
    fee, from_clinic = service.effective_fee(
        doctor.consultation_fee, clinic, "consultation_fee"
    )
    return DoctorSummary(
        id=doctor.id,
        display_name=doctor.display_name,
        full_name=doctor.full_name,
        title=doctor.title,
        speciality=doctor.speciality,
        qualifications=doctor.qualifications,
        room=doctor.room,
        status=doctor.status,
        consultation_fee=fee,
        fee_from_clinic=from_clinic,
        slot_duration_minutes=service.effective_slot_minutes(doctor, clinic),
        working_days=row.working_days,
        has_account=doctor.user_id is not None,
        created_at=doctor.created_at,
    )


async def _read(
    session: AsyncSession, organization_id: uuid.UUID, doctor_id: uuid.UUID
) -> DoctorOut:
    row = await DoctorRepository(session, organization_id).with_working_days(doctor_id)
    if row is None:
        raise service.DoctorNotFound

    doctor = row.doctor
    clinic = await _clinic(session, organization_id)

    schedule = await ScheduleRepository(session, organization_id).for_doctor(doctor_id)
    leaves = await LeaveRepository(session, organization_id).for_doctor(
        doctor_id, ending_after=service.clinic_today(clinic)
    )
    names = await names_of(session, {doctor.user_id} if doctor.user_id else set())

    follow_up, follow_up_from_clinic = service.effective_fee(
        doctor.follow_up_fee, clinic, "follow_up_fee"
    )

    return DoctorOut(
        **_summary(row, clinic).model_dump(),
        first_name=doctor.first_name,
        last_name=doctor.last_name,
        registration_number=doctor.registration_number,
        years_of_experience=doctor.years_of_experience,
        phone=doctor.phone,
        email=doctor.email,
        languages=doctor.languages,
        bio=doctor.bio,
        follow_up_fee=follow_up,
        follow_up_fee_from_clinic=follow_up_from_clinic,
        # Carried separately from the figure that applies, so the edit form
        # can show a blank box that means "follow the clinic" rather than
        # writing the clinic's number into the profile the moment it opens.
        own_consultation_fee=(
            None if doctor.consultation_fee is None else f"{doctor.consultation_fee:.2f}"
        ),
        own_follow_up_fee=(
            None if doctor.follow_up_fee is None else f"{doctor.follow_up_fee:.2f}"
        ),
        own_slot_duration_minutes=doctor.slot_duration_minutes,
        user_id=doctor.user_id,
        account_name=names.get(doctor.user_id) if doctor.user_id else None,
        deactivated_at=doctor.deactivated_at,
        schedule=[ScheduleBlockOut.model_validate(block) for block in schedule],
        leaves=[LeaveOut.model_validate(leave) for leave in leaves],
    )


@router.get("/doctors")
async def list_doctors(
    session: DbSession,
    query: str = Query(default="", max_length=120, alias="q"),
    speciality: str = Query(default="", max_length=80),
    status: str = Query(default=ACTIVE, pattern="^(active|inactive|all)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    _: Caller = Depends(requires("doctor:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DoctorPage:
    clinic = await _clinic(session, organization_id)
    found, total = await DoctorRepository(session, organization_id).search(
        query=query,
        speciality=speciality,
        status=None if status == "all" else status,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return DoctorPage(
        items=[_summary(row, clinic) for row in found],
        total=total,
        page=page,
        per_page=per_page,
        pages=max(math.ceil(total / per_page), 1),
    )


@router.get("/doctors/specialities")
async def list_specialities(
    session: DbSession,
    status: str = Query(default=ACTIVE, pattern="^(active|inactive|all)$"),
    _: Caller = Depends(requires("doctor:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> list[str]:
    """What this clinic actually offers, rather than a fixed list every
    clinic has to pick the wrong answer from.

    Takes the same status as the list so the two agree; a filter that can
    only ever come back empty is worse than no filter.
    """
    return await DoctorRepository(session, organization_id).specialities(
        None if status == "all" else status
    )


@router.post("/doctors", status_code=201)
async def add_doctor(
    session: DbSession,
    body: DoctorCreate,
    trail: Trail,
    _: Caller = Depends(requires("doctor:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DoctorOut:
    doctor = await service.add(session, organization_id=organization_id, body=body)
    found = await _read(session, organization_id, doctor.id)
    await trail("doctor.added", "doctor", found.id, found.display_name)
    return found


@router.get("/doctors/{doctor_id}")
async def read_doctor(
    session: DbSession,
    doctor_id: uuid.UUID,
    _: Caller = Depends(requires("doctor:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DoctorOut:
    return await _read(session, organization_id, doctor_id)


@router.patch("/doctors/{doctor_id}")
async def update_doctor(
    session: DbSession,
    doctor_id: uuid.UUID,
    body: DoctorUpdate,
    trail: Trail,
    _: Caller = Depends(requires("doctor:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DoctorOut:
    fields = body.model_dump(exclude_unset=True)
    current = await DoctorRepository(session, organization_id).get(doctor_id)
    before = events.snapshot(current, fields) if current else {}
    await service.update(
        session, organization_id=organization_id, doctor_id=doctor_id, body=body
    )
    found = await _read(session, organization_id, doctor_id)
    changed = await DoctorRepository(session, organization_id).get(doctor_id)
    moved = events.difference(before, events.snapshot(changed, fields)) if changed else None
    if moved:
        await trail("doctor.changed", "doctor", found.id, found.display_name, moved)
    return found


@router.post("/doctors/{doctor_id}/deactivate")
async def deactivate_doctor(
    session: DbSession,
    doctor_id: uuid.UUID,
    trail: Trail,
    _: Caller = Depends(requires("doctor:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DoctorOut:
    """Takes a doctor off the lists without losing their rota or anything
    signed in their name."""
    await service.set_active(
        session, organization_id=organization_id, doctor_id=doctor_id, active=False
    )
    found = await _read(session, organization_id, doctor_id)
    await trail("doctor.deactivated", "doctor", found.id, found.display_name)
    return found


@router.post("/doctors/{doctor_id}/restore")
async def restore_doctor(
    session: DbSession,
    doctor_id: uuid.UUID,
    trail: Trail,
    _: Caller = Depends(requires("doctor:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DoctorOut:
    await service.set_active(
        session, organization_id=organization_id, doctor_id=doctor_id, active=True
    )
    found = await _read(session, organization_id, doctor_id)
    await trail("doctor.restored", "doctor", found.id, found.display_name)
    return found


@router.get("/doctors/{doctor_id}/schedule")
async def read_schedule(
    session: DbSession,
    doctor_id: uuid.UUID,
    _: Caller = Depends(requires("doctor:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> list[ScheduleBlockOut]:
    await service.fetch(session, organization_id=organization_id, doctor_id=doctor_id)
    blocks = await ScheduleRepository(session, organization_id).for_doctor(doctor_id)
    return [ScheduleBlockOut.model_validate(block) for block in blocks]


@router.put("/doctors/{doctor_id}/schedule")
async def write_schedule(
    session: DbSession,
    doctor_id: uuid.UUID,
    body: ScheduleWrite,
    trail: Trail,
    _: Caller = Depends(requires("doctor:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> list[ScheduleBlockOut]:
    """The whole week at once. Sending an empty list clears it."""
    blocks = await service.replace_schedule(
        session, organization_id=organization_id, doctor_id=doctor_id, body=body
    )
    written = [ScheduleBlockOut.model_validate(block) for block in blocks]
    found = await _read(session, organization_id, doctor_id)
    week = [
        f"{_DAYS[block.day_of_week]} {block.start_time:%H:%M}-{block.end_time:%H:%M}"
        for block in written
    ]
    await trail(
        "doctor.hours_set",
        "doctor",
        found.id,
        found.display_name,
        {"week": ", ".join(week) or "No hours"},
    )
    return written


@router.get("/doctors/{doctor_id}/availability")
async def read_availability(
    session: DbSession,
    doctor_id: uuid.UUID,
    date: dt.date | None = Query(default=None),
    _: Caller = Depends(requires("doctor:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Availability:
    clinic = await _clinic(session, organization_id)
    day = date or service.clinic_today(clinic)
    found = await service.availability(
        session,
        organization_id=organization_id,
        clinic=clinic,
        doctor_id=doctor_id,
        day=day,
    )
    return Availability.model_validate(found)


@router.post("/doctors/{doctor_id}/leaves", status_code=201)
async def record_leave(
    session: DbSession,
    doctor_id: uuid.UUID,
    body: LeaveWrite,
    trail: Trail,
    caller: Caller = Depends(requires("doctor:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LeaveOut:
    leave = await service.add_leave(
        session,
        organization_id=organization_id,
        doctor_id=doctor_id,
        actor_id=caller.user_id,
        body=body,
    )
    written = LeaveOut.model_validate(leave)
    found = await _read(session, organization_id, doctor_id)
    await trail(
        "doctor.leave_added",
        "doctor",
        found.id,
        found.display_name,
        {"from": written.starts_on, "to": written.ends_on, "reason": written.reason},
    )
    return written


@router.delete("/doctors/{doctor_id}/leaves/{leave_id}")
async def cancel_leave(
    session: DbSession,
    doctor_id: uuid.UUID,
    leave_id: uuid.UUID,
    trail: Trail,
    _: Caller = Depends(requires("doctor:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Removed:
    found = await _read(session, organization_id, doctor_id)
    leave = await LeaveRepository(session, organization_id).get(leave_id)
    held = {"from": leave.starts_on, "to": leave.ends_on} if leave else None
    await service.remove_leave(
        session,
        organization_id=organization_id,
        doctor_id=doctor_id,
        leave_id=leave_id,
    )
    await trail("doctor.leave_removed", "doctor", found.id, found.display_name, held)
    return Removed()
