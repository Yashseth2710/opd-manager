"""Appointments: the day's book, booking into it, and what happens after.

A doctor's role sees only their own list. Everything outside it reads as
absent, the same as another clinic's appointment would.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.core.exceptions import NotFound
from app.models import Organization
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentDay,
    AppointmentDetail,
    AppointmentUpdate,
    CancelWrite,
    PatientAppointments,
)
from app.services import appointments as service
from app.services.doctors import clinic_today

router = APIRouter(tags=["appointments"])


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    return clinic


async def _reach(
    session: AsyncSession, organization_id: uuid.UUID, caller: Caller
) -> service.Reach:
    return await service.reach_of(
        session, organization_id=organization_id, user_id=caller.user_id, role=caller.role
    )


async def _detail(
    session: AsyncSession,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: service.Reach,
    appointment_id: uuid.UUID,
) -> AppointmentDetail:
    found = await service.detail(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        appointment_id=appointment_id,
    )
    return AppointmentDetail.model_validate(found)


@router.get("/appointments")
async def list_day(
    session: DbSession,
    date: dt.date | None = Query(default=None),
    doctor_id: uuid.UUID | None = Query(default=None),
    caller: Caller = Depends(requires("appointment:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AppointmentDay:
    """One day of the book. Without a date, the clinic's today rather than the
    server's, which is a different day for part of every evening."""
    clinic = await _clinic(session, organization_id)
    found = await service.day_list(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=await _reach(session, organization_id, caller),
        day=date or clinic_today(clinic),
        doctor_id=doctor_id,
    )
    return AppointmentDay.model_validate(found)


@router.get("/patients/{patient_id}/appointments")
async def list_for_patient(
    session: DbSession,
    patient_id: uuid.UUID,
    caller: Caller = Depends(requires("appointment:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> PatientAppointments:
    clinic = await _clinic(session, organization_id)
    found = await service.for_patient(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=await _reach(session, organization_id, caller),
        patient_id=patient_id,
    )
    return PatientAppointments.model_validate(found)


@router.post("/appointments", status_code=201)
async def book(
    session: DbSession,
    body: AppointmentCreate,
    caller: Caller = Depends(requires("appointment:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AppointmentDetail:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    appointment = await service.book(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        actor_id=caller.user_id,
        body=body,
    )
    return await _detail(session, organization_id, clinic, reach, appointment.id)


@router.get("/appointments/{appointment_id}")
async def read_appointment(
    session: DbSession,
    appointment_id: uuid.UUID,
    caller: Caller = Depends(requires("appointment:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AppointmentDetail:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    return await _detail(session, organization_id, clinic, reach, appointment_id)


@router.patch("/appointments/{appointment_id}")
async def change_appointment(
    session: DbSession,
    appointment_id: uuid.UUID,
    body: AppointmentUpdate,
    caller: Caller = Depends(requires("appointment:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AppointmentDetail:
    """Moves an appointment, corrects its details, or both."""
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.update(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        actor_id=caller.user_id,
        appointment_id=appointment_id,
        body=body,
    )
    return await _detail(session, organization_id, clinic, reach, appointment_id)


@router.post("/appointments/{appointment_id}/confirm")
async def confirm_appointment(
    session: DbSession,
    appointment_id: uuid.UUID,
    caller: Caller = Depends(requires("appointment:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AppointmentDetail:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.confirm(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        actor_id=caller.user_id,
        appointment_id=appointment_id,
    )
    return await _detail(session, organization_id, clinic, reach, appointment_id)


@router.post("/appointments/{appointment_id}/cancel")
async def cancel_appointment(
    session: DbSession,
    appointment_id: uuid.UUID,
    body: CancelWrite,
    caller: Caller = Depends(requires("appointment:cancel")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AppointmentDetail:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.cancel(
        session,
        organization_id=organization_id,
        reach=reach,
        actor_id=caller.user_id,
        appointment_id=appointment_id,
        reason=body.reason,
    )
    return await _detail(session, organization_id, clinic, reach, appointment_id)


@router.post("/appointments/{appointment_id}/no-show")
async def mark_no_show(
    session: DbSession,
    appointment_id: uuid.UUID,
    caller: Caller = Depends(requires("appointment:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AppointmentDetail:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.mark_no_show(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        actor_id=caller.user_id,
        appointment_id=appointment_id,
    )
    return await _detail(session, organization_id, clinic, reach, appointment_id)
