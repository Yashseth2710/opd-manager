"""Lab orders and their results, and the list of tests they are picked from."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, Trail, current_tenant, requires
from app.core.exceptions import NotFound
from app.models import Organization
from app.models import notification as kinds
from app.schemas.lab import (
    LabCancel,
    LabCatalogue,
    LabOrderIn,
    LabOrderOut,
    LabOrderPage,
    LabResultIn,
    Removed,
)
from app.services import appointments, events
from app.services import lab as service
from app.services.appointments import Reach

router = APIRouter(tags=["lab"])


def _named(order: LabOrderOut) -> str:
    return (
        f"{order.test_name}, {order.order_number}, for "
        f"{order.patient.full_name} ({order.patient.patient_number})"
    )


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
    session: AsyncSession, organization_id: uuid.UUID, caller: Caller, order_id: uuid.UUID
) -> LabOrderOut:
    found = await service.detail(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=await _reach(session, organization_id, caller),
        may_create=caller.may("lab:create"),
        may_update=caller.may("lab:update"),
        order_id=order_id,
    )
    return LabOrderOut.model_validate(found)


@router.get("/lab-tests")
async def list_tests(
    session: DbSession,
    caller: Caller = Depends(requires("lab:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LabCatalogue:
    return LabCatalogue.model_validate(
        await service.the_list(session, organization_id=organization_id)
    )


@router.get("/lab-orders")
async def list_orders(
    session: DbSession,
    patient_id: uuid.UUID | None = Query(default=None),
    consultation_id: uuid.UUID | None = Query(default=None),
    doctor_id: uuid.UUID | None = Query(default=None),
    mine: bool = Query(default=False),
    show: Literal["waiting", "to_review", "reviewed", "cancelled", "open"] | None = Query(
        default=None
    ),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    caller: Caller = Depends(requires("lab:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LabOrderPage:
    """Waiting ones oldest first, since the oldest is the one that is late;
    anything else newest first. `mine` narrows a doctor's list to the tests
    they ordered themselves."""
    if mine:
        reach = await _reach(session, organization_id, caller)
        if reach.unlinked:
            return LabOrderPage(
                items=[],
                total=0,
                counts=dict.fromkeys(("ordered", "resulted", "reviewed", "cancelled"), 0),
            )
        if reach.narrowed:
            doctor_id = reach.doctor_id
    found = await service.listed(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        patient_id=patient_id,
        consultation_id=consultation_id,
        doctor_id=doctor_id,
        show=show,
        typed=q.strip() if q and q.strip() else None,
        limit=limit,
        offset=offset,
    )
    return LabOrderPage.model_validate(found)


@router.post("/lab-orders", status_code=201)
async def order_test(
    session: DbSession,
    body: LabOrderIn,
    trail: Trail,
    caller: Caller = Depends(requires("lab:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LabOrderOut:
    order_id = await service.order(
        session,
        organization_id=organization_id,
        reach=await _reach(session, organization_id, caller),
        actor_id=caller.user_id,
        body=body,
    )
    found = await _answer(session, organization_id, caller, order_id)
    await trail(
        "lab.ordered",
        "lab_order",
        found.id,
        _named(found),
        {"urgent": True} if found.urgent else None,
    )
    return found


@router.get("/lab-orders/{order_id}")
async def read_order(
    session: DbSession,
    order_id: uuid.UUID,
    caller: Caller = Depends(requires("lab:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LabOrderOut:
    return await _answer(session, organization_id, caller, order_id)


@router.delete("/lab-orders/{order_id}")
async def remove_order(
    session: DbSession,
    order_id: uuid.UUID,
    trail: Trail,
    caller: Caller = Depends(requires("lab:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Removed:
    """Only while the visit is open and nothing has come back."""
    removed = await _answer(session, organization_id, caller, order_id)
    await service.remove(
        session,
        organization_id=organization_id,
        reach=await _reach(session, organization_id, caller),
        order_id=order_id,
    )
    await trail("lab.removed", "lab_order", removed.id, _named(removed))
    return Removed()


@router.post("/lab-orders/{order_id}/cancel")
async def cancel_order(
    session: DbSession,
    order_id: uuid.UUID,
    body: LabCancel,
    trail: Trail,
    caller: Caller = Depends(requires("lab:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LabOrderOut:
    """By the doctor who ordered it, or by whoever records results."""
    await service.cancel(
        session,
        organization_id=organization_id,
        reach=await _reach(session, organization_id, caller),
        may_create=caller.may("lab:create"),
        may_update=caller.may("lab:update"),
        actor_id=caller.user_id,
        order_id=order_id,
        reason=body.reason,
    )
    found = await _answer(session, organization_id, caller, order_id)
    await trail(
        "lab.cancelled", "lab_order", found.id, _named(found), {"reason": found.cancel_reason}
    )
    return found


@router.put("/lab-orders/{order_id}/result")
async def record_result(
    session: DbSession,
    order_id: uuid.UUID,
    body: LabResultIn,
    trail: Trail,
    caller: Caller = Depends(requires("lab:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LabOrderOut:
    """The whole report. A value left out is taken off."""
    before = await _answer(session, organization_id, caller, order_id)
    await service.record(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        reach=await _reach(session, organization_id, caller),
        actor_id=caller.user_id,
        order_id=order_id,
        body=body,
    )
    found = await _answer(session, organization_id, caller, order_id)
    first_time = before.status == "ordered"
    await trail(
        "lab.resulted" if first_time else "lab.result_changed",
        "lab_order",
        found.id,
        _named(found),
        {"flagged": found.flagged} if found.flagged else None,
    )
    if first_time:
        flagged = f", {found.flagged} outside range" if found.flagged else ""
        await trail.tell(
            await events.doctor_account(session, organization_id, found.doctor.id),
            events.Notice(
                kind=kinds.LAB_RESULT,
                title=f"{found.test_name} result in for {found.patient.full_name}{flagged}",
                body=f"{found.order_number}. Mark it as seen once you have read it.",
                link=f"/lab/{found.id}",
            ),
        )
    return found


@router.delete("/lab-orders/{order_id}/result")
async def clear_result(
    session: DbSession,
    order_id: uuid.UUID,
    trail: Trail,
    caller: Caller = Depends(requires("lab:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LabOrderOut:
    """For a report typed against the wrong order, before it has been seen."""
    await service.clear(
        session,
        organization_id=organization_id,
        reach=await _reach(session, organization_id, caller),
        order_id=order_id,
    )
    found = await _answer(session, organization_id, caller, order_id)
    await trail("lab.result_cleared", "lab_order", found.id, _named(found))
    return found


@router.post("/lab-orders/{order_id}/review")
async def review_result(
    session: DbSession,
    order_id: uuid.UUID,
    trail: Trail,
    caller: Caller = Depends(requires("lab:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LabOrderOut:
    await service.review(
        session,
        organization_id=organization_id,
        reach=await _reach(session, organization_id, caller),
        actor_id=caller.user_id,
        order_id=order_id,
    )
    found = await _answer(session, organization_id, caller, order_id)
    await trail("lab.reviewed", "lab_order", found.id, _named(found))
    return found
