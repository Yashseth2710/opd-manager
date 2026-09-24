"""How the clinic has been doing, over whatever stretch of days is asked for."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.core.exceptions import NotFound
from app.models import Organization
from app.schemas.report import Range, Report
from app.services import appointments
from app.services import reports as service

router = APIRouter(tags=["reports"])

Chosen = Query(default="week", alias="range")
First = Query(default=None, alias="from")
Last = Query(default=None, alias="to")


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    return clinic


async def _asked(
    session: AsyncSession,
    organization_id: uuid.UUID,
    caller: Caller,
    chosen: str,
    first: dt.date | None,
    last: dt.date | None,
) -> tuple[Organization, appointments.Reach, dict[str, object]]:
    clinic = await _clinic(session, organization_id)
    reach = await appointments.reach_of(
        session, organization_id=organization_id, user_id=caller.user_id, role=caller.role
    )
    return clinic, reach, service.span_for(clinic, chosen, first, last)


@router.get("/reports/summary")
async def read_report(
    session: DbSession,
    chosen: Range = Chosen,
    first: dt.date | None = First,
    last: dt.date | None = Last,
    caller: Caller = Depends(requires("reports:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Report:
    """The clinic's figures, or one doctor's own when a doctor asks."""
    clinic, reach, span = await _asked(session, organization_id, caller, chosen, first, last)
    found = await service.over(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        span=span,
    )
    return Report.model_validate(found)


@router.get("/reports/day-book.csv")
async def download_day_book(
    session: DbSession,
    chosen: Range = Chosen,
    first: dt.date | None = First,
    last: dt.date | None = Last,
    caller: Caller = Depends(requires("reports:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Response:
    """The payments behind the figures, one to a line, for a spreadsheet."""
    clinic, reach, span = await _asked(session, organization_id, caller, chosen, first, last)
    content = await service.day_book(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        span=span,
    )
    name = f"day-book-{span['first_day']}-to-{span['last_day']}.csv"
    return Response(
        # The byte order mark is there so Excel opens a name with an
        # accent in it as UTF-8 instead of guessing the local codepage.
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
        },
    )
