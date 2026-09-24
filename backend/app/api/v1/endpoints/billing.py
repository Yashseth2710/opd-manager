"""Bills, the money taken against them, and the day's takings."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, DbSession, current_tenant, requires
from app.core.exceptions import NotFound, ValidationFailed
from app.models import Organization
from app.schemas.billing import (
    DaySummary,
    InvoiceChange,
    InvoiceIn,
    InvoiceOut,
    InvoicePage,
    LinkIn,
    LinkMade,
    PastLine,
    PaymentIn,
    RefundIn,
    Removed,
    Starting,
    UnbilledPage,
    VoidIn,
)
from app.services import billing as service
from app.services import payment_links
from app.services.billing_pdf import render
from app.services.doctors import clinic_today, clinic_zone

router = APIRouter(tags=["billing"])

RequestKey = Header(default=None, alias="Idempotency-Key", max_length=100)


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    return clinic


async def _answer(
    session: AsyncSession, organization_id: uuid.UUID, caller: Caller, invoice_id: uuid.UUID
) -> InvoiceOut:
    found = await service.detail(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        permissions=caller.permissions,
        role=caller.role,
        invoice_id=invoice_id,
    )
    return InvoiceOut.model_validate(found)


@router.get("/invoices")
async def list_invoices(
    session: DbSession,
    show: Literal["to_collect", "drafts", "paid", "void", "all"] = Query(default="all"),
    patient_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    since: dt.date | None = Query(default=None, alias="from"),
    until: dt.date | None = Query(default=None, alias="to"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    caller: Caller = Depends(requires("billing:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> InvoicePage:
    """Newest first, by when each was issued, or made for a draft. `from`
    and `to` are the clinic's dates and include both ends."""
    found = await service.listed(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        show=show,
        patient_id=patient_id,
        typed=q.strip() if q and q.strip() else None,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return InvoicePage.model_validate(found)


@router.get("/invoices/summary")
async def day_summary(
    session: DbSession,
    day: dt.date | None = Query(default=None, alias="date"),
    caller: Caller = Depends(requires("billing:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DaySummary:
    """What came in on the day, by how it was paid. Today at the clinic
    unless a date is given."""
    clinic = await _clinic(session, organization_id)
    found = await service.summary(
        session, organization_id=organization_id, clinic=clinic, day=day or clinic_today(clinic)
    )
    return DaySummary.model_validate(found)


@router.get("/invoices/unbilled")
async def unbilled_visits(
    session: DbSession,
    day: dt.date | None = Query(default=None, alias="date"),
    caller: Caller = Depends(requires("billing:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> UnbilledPage:
    """Patients seen that day who have no bill yet."""
    clinic = await _clinic(session, organization_id)
    found = await service.unbilled(
        session, organization_id=organization_id, clinic=clinic, day=day or clinic_today(clinic)
    )
    return UnbilledPage.model_validate(found)


@router.get("/invoices/start")
async def start_invoice(
    session: DbSession,
    patient_id: uuid.UUID | None = Query(default=None),
    queue_entry_id: uuid.UUID | None = Query(default=None),
    caller: Caller = Depends(requires("billing:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Starting:
    """What a new bill starts from: for a visit, the doctor's fee, or their
    follow-up fee, and the tests ordered at it."""
    found = await service.starting(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        patient_id=patient_id,
        queue_entry_id=queue_entry_id,
    )
    return Starting.model_validate(found)


@router.get("/invoices/lines")
async def past_lines(
    session: DbSession,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=8, ge=1, le=30),
    caller: Caller = Depends(requires("billing:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> list[PastLine]:
    """What the clinic has charged for before, at the price it last charged."""
    found = await service.past_lines(
        session,
        organization_id=organization_id,
        typed=q.strip() if q and q.strip() else None,
        limit=limit,
    )
    return [PastLine.model_validate(each) for each in found]


@router.post("/invoices", status_code=201)
async def raise_invoice(
    session: DbSession,
    body: InvoiceIn,
    response: Response,
    key: str | None = RequestKey,
    caller: Caller = Depends(requires("billing:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> InvoiceOut:
    """With `issue`, straight out as a numbered bill. The same
    Idempotency-Key again answers with the bill the first request made."""
    invoice_id, made = await service.create(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        actor_id=caller.user_id,
        body=body,
        key=service.request_key(key),
    )
    if not made:
        response.status_code = 200
    return await _answer(session, organization_id, caller, invoice_id)


@router.get("/invoices/{invoice_id}")
async def read_invoice(
    session: DbSession,
    invoice_id: uuid.UUID,
    caller: Caller = Depends(requires("billing:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> InvoiceOut:
    return await _answer(session, organization_id, caller, invoice_id)


@router.patch("/invoices/{invoice_id}")
async def change_invoice(
    session: DbSession,
    invoice_id: uuid.UUID,
    body: InvoiceChange,
    caller: Caller = Depends(requires("billing:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> InvoiceOut:
    """Drafts only. An issued bill is voided and raised again instead."""
    await service.change(
        session, organization_id=organization_id, invoice_id=invoice_id, body=body
    )
    return await _answer(session, organization_id, caller, invoice_id)


@router.delete("/invoices/{invoice_id}")
async def discard_invoice(
    session: DbSession,
    invoice_id: uuid.UUID,
    caller: Caller = Depends(requires("billing:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Removed:
    """Drafts only, since they have no number and have taken nothing."""
    await service.discard(session, organization_id=organization_id, invoice_id=invoice_id)
    return Removed()


@router.post("/invoices/{invoice_id}/issue")
async def issue_invoice(
    session: DbSession,
    invoice_id: uuid.UUID,
    caller: Caller = Depends(requires("billing:create")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> InvoiceOut:
    await service.issue(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        actor_id=caller.user_id,
        invoice_id=invoice_id,
    )
    return await _answer(session, organization_id, caller, invoice_id)


@router.post("/invoices/{invoice_id}/void")
async def void_invoice(
    session: DbSession,
    invoice_id: uuid.UUID,
    body: VoidIn,
    caller: Caller = Depends(requires("billing:update")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> InvoiceOut:
    """Only once any money taken on it has been given back."""
    await service.void(
        session,
        organization_id=organization_id,
        actor_id=caller.user_id,
        invoice_id=invoice_id,
        reason=body.reason,
    )
    return await _answer(session, organization_id, caller, invoice_id)


@router.post("/invoices/{invoice_id}/payments", status_code=201)
async def take_payment(
    session: DbSession,
    invoice_id: uuid.UUID,
    body: PaymentIn,
    key: str | None = RequestKey,
    caller: Caller = Depends(requires("payment:record")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> InvoiceOut:
    """Part of what is owed, or all of it. Taking money on a draft issues it."""
    await service.pay(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        actor_id=caller.user_id,
        may_issue=caller.may("billing:create"),
        invoice_id=invoice_id,
        body=body,
        key=service.request_key(key),
    )
    return await _answer(session, organization_id, caller, invoice_id)


@router.post("/invoices/{invoice_id}/refunds", status_code=201)
async def give_back(
    session: DbSession,
    invoice_id: uuid.UUID,
    body: RefundIn,
    key: str | None = RequestKey,
    caller: Caller = Depends(requires("payment:record")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> InvoiceOut:
    """The clinic admin only, and never more than was taken."""
    await service.refund(
        session,
        organization_id=organization_id,
        role=caller.role,
        actor_id=caller.user_id,
        invoice_id=invoice_id,
        body=body,
        key=service.request_key(key),
    )
    return await _answer(session, organization_id, caller, invoice_id)


@router.post("/invoices/{invoice_id}/payment-link", status_code=201)
async def send_payment_link(
    session: DbSession,
    invoice_id: uuid.UUID,
    body: LinkIn,
    caller: Caller = Depends(requires("payment:record")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> LinkMade:
    """A link the patient pays from, for what is still owed.

    The address comes back once and is not kept, so asking again raises a
    fresh link and takes the previous one out of circulation.
    """
    made = await payment_links.raise_link(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        actor_id=caller.user_id,
        invoice_id=invoice_id,
        send_it=body.send,
        to=body.email,
    )
    return LinkMade.model_validate(made)


@router.delete("/invoices/{invoice_id}/payment-link")
async def cancel_payment_link(
    session: DbSession,
    invoice_id: uuid.UUID,
    caller: Caller = Depends(requires("payment:record")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> InvoiceOut:
    """Stops the open link working. Money already paid through it stays."""
    await payment_links.cancel_link(
        session, organization_id=organization_id, invoice_id=invoice_id
    )
    return await _answer(session, organization_id, caller, invoice_id)


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(
    session: DbSession,
    invoice_id: uuid.UUID,
    caller: Caller = Depends(requires("billing:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Response:
    """The bill to print or send, made fresh each time."""
    found = await _answer(session, organization_id, caller, invoice_id)
    if found.status == "draft":
        raise ValidationFailed(
            {"status": "Issue the bill before printing it."},
            "Issue the bill before printing it.",
        )
    clinic = await _clinic(session, organization_id)
    content = render(found.model_dump(), clinic=clinic, zone=clinic_zone(clinic))
    name = (found.invoice_number or "bill").replace("/", "-")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{name}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )
