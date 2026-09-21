"""The day's queue, and checking patients into it.

A doctor's role sees and moves only their own line. Everything outside it
reads as absent, the same as another clinic's would.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.core.exceptions import NotFound
from app.models import Organization
from app.schemas.appointment import AppointmentDetail
from app.schemas.queue import CheckIn, PriorityWrite, QueueDay, QueueEntryOut, WalkIn
from app.services import appointments
from app.services import queue as service

router = APIRouter(tags=["queue"])


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


async def _entry(
    session: AsyncSession,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: appointments.Reach,
    entry_id: uuid.UUID,
    caller: Caller,
) -> QueueEntryOut:
    found = await service.one(
        session, organization_id=organization_id, clinic=clinic, reach=reach, entry_id=entry_id
    )
    shown = QueueEntryOut.model_validate(found)
    if not caller.may("billing:read"):
        shown.invoice = None
    return shown


def _without_bills(day: QueueDay) -> QueueDay:
    """The day as somebody who does not read bills sees it."""
    for lane in day.lanes:
        for entry in (lane.now_seeing, lane.called, *lane.waiting, *lane.skipped, *lane.done):
            if entry is not None:
                entry.invoice = None
    return day


@router.get("/queue")
async def read_queue(
    session: DbSession,
    doctor_id: uuid.UUID | None = Query(default=None),
    caller: Caller = Depends(requires("appointment:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueDay:
    """Today's queue at the clinic, by the clinic's clock. Polled, so kept to
    a handful of queries whatever the size of the day."""
    clinic = await _clinic(session, organization_id)
    found = await service.day(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=await _reach(session, organization_id, caller),
        doctor_id=doctor_id,
    )
    day = QueueDay.model_validate(found)
    return day if caller.may("billing:read") else _without_bills(day)


@router.post("/appointments/{appointment_id}/check-in", status_code=201)
async def check_in(
    session: DbSession,
    appointment_id: uuid.UUID,
    body: CheckIn,
    caller: Caller = Depends(requires("queue:checkin")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    entry = await service.check_in(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        actor_id=caller.user_id,
        appointment_id=appointment_id,
        priority=body.priority,
    )
    return await _entry(session, organization_id, clinic, reach, entry.id, caller)


@router.post("/queue/walk-in", status_code=201)
async def walk_in(
    session: DbSession,
    body: WalkIn,
    caller: Caller = Depends(requires("queue:checkin")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    entry = await service.walk_in(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        actor_id=caller.user_id,
        body=body,
    )
    return await _entry(session, organization_id, clinic, reach, entry.id, caller)


@router.get("/queue/{entry_id}")
async def read_entry(
    session: DbSession,
    entry_id: uuid.UUID,
    caller: Caller = Depends(requires("appointment:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    return await _entry(session, organization_id, clinic, reach, entry_id, caller)


@router.post("/queue/{entry_id}/call")
async def call(
    session: DbSession,
    entry_id: uuid.UUID,
    caller: Caller = Depends(requires("queue:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.call(
        session, organization_id=organization_id, clinic=clinic, reach=reach, entry_id=entry_id
    )
    return await _entry(session, organization_id, clinic, reach, entry_id, caller)


@router.post("/queue/{entry_id}/start")
async def start(
    session: DbSession,
    entry_id: uuid.UUID,
    caller: Caller = Depends(requires("queue:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.start(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        actor_id=caller.user_id,
        entry_id=entry_id,
    )
    return await _entry(session, organization_id, clinic, reach, entry_id, caller)


@router.post("/queue/{entry_id}/complete")
async def complete(
    session: DbSession,
    entry_id: uuid.UUID,
    caller: Caller = Depends(requires("queue:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.complete(
        session,
        organization_id=organization_id,
        reach=reach,
        actor_id=caller.user_id,
        entry_id=entry_id,
    )
    return await _entry(session, organization_id, clinic, reach, entry_id, caller)


@router.post("/queue/{entry_id}/skip")
async def skip(
    session: DbSession,
    entry_id: uuid.UUID,
    caller: Caller = Depends(requires("queue:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.skip(session, organization_id=organization_id, reach=reach, entry_id=entry_id)
    return await _entry(session, organization_id, clinic, reach, entry_id, caller)


@router.post("/queue/{entry_id}/recall")
async def recall(
    session: DbSession,
    entry_id: uuid.UUID,
    caller: Caller = Depends(requires("queue:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.recall(
        session, organization_id=organization_id, clinic=clinic, reach=reach, entry_id=entry_id
    )
    return await _entry(session, organization_id, clinic, reach, entry_id, caller)


@router.post("/queue/{entry_id}/no-show")
async def mark_gone(
    session: DbSession,
    entry_id: uuid.UUID,
    caller: Caller = Depends(requires("queue:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.mark_gone(
        session,
        organization_id=organization_id,
        reach=reach,
        actor_id=caller.user_id,
        entry_id=entry_id,
    )
    return await _entry(session, organization_id, clinic, reach, entry_id, caller)


@router.patch("/queue/{entry_id}")
async def set_priority(
    session: DbSession,
    entry_id: uuid.UUID,
    body: PriorityWrite,
    caller: Caller = Depends(requires("queue:manage")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> QueueEntryOut:
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    await service.set_priority(
        session,
        organization_id=organization_id,
        reach=reach,
        entry_id=entry_id,
        priority=body.priority,
    )
    return await _entry(session, organization_id, clinic, reach, entry_id, caller)


@router.delete("/queue/{entry_id}")
async def undo_check_in(
    session: DbSession,
    entry_id: uuid.UUID,
    caller: Caller = Depends(requires("queue:checkin")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> AppointmentDetail | None:
    """Takes back a check-in made by mistake. Answers with the appointment as
    it stands again, or nothing for a walk-in, who had none."""
    clinic = await _clinic(session, organization_id)
    reach = await _reach(session, organization_id, caller)
    appointment_id = await service.undo(
        session,
        organization_id=organization_id,
        reach=reach,
        actor_id=caller.user_id,
        entry_id=entry_id,
    )
    if appointment_id is None:
        return None
    found = await appointments.detail(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        appointment_id=appointment_id,
    )
    return AppointmentDetail.model_validate(found)
