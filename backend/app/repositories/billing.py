"""Queries for bills, their lines and the money taken against them."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Doctor,
    Invoice,
    InvoiceItem,
    Patient,
    Payment,
    PaymentLink,
    User,
    billing,
)
from app.repositories.appointments import allergy_count
from app.repositories.base import TenantScopedRepository
from app.repositories.prescriptions import _as_typed


@dataclass
class Billed:
    invoice: Invoice
    patient: Patient
    allergy_count: int
    doctor: Doctor | None
    items: list[InvoiceItem] = field(default_factory=list)


class InvoiceRepository(TenantScopedRepository[Invoice]):
    model = Invoice

    def _joined(self) -> Select[Any]:
        return (
            select(Invoice, Patient, allergy_count(), Doctor)
            .join(Patient, Patient.id == Invoice.patient_id)
            .outerjoin(Doctor, Doctor.id == Invoice.doctor_id)
            .where(Invoice.organization_id == self.organization_id)
        )

    async def _rows(self, statement: Select[Any]) -> list[Billed]:
        result = await self.session.execute(statement)
        found = [
            Billed(invoice=row[0], patient=row[1], allergy_count=row[2], doctor=row[3])
            for row in result.all()
        ]
        if found:
            by_id = {each.invoice.id: each for each in found}
            lines = await self.session.execute(
                select(InvoiceItem)
                .where(InvoiceItem.organization_id == self.organization_id)
                .where(InvoiceItem.invoice_id.in_(by_id))
                .order_by(InvoiceItem.invoice_id, InvoiceItem.position)
            )
            for line in lines.scalars().all():
                by_id[line.invoice_id].items.append(line)
        return found

    async def one(self, invoice_id: uuid.UUID, *, lock: bool = False) -> Billed | None:
        statement = (
            self._joined()
            .where(Invoice.id == invoice_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update(of=Invoice)
        found = await self._rows(statement)
        return found[0] if found else None

    async def by_request(self, key: str) -> Invoice | None:
        result = await self.session.execute(self.query().where(Invoice.request_key == key))
        return result.scalar_one_or_none()

    async def live_for_visit(self, queue_entry_id: uuid.UUID) -> Invoice | None:
        result = await self.session.execute(
            self.query()
            .where(Invoice.queue_entry_id == queue_entry_id)
            .where(Invoice.status != billing.VOID)
        )
        return result.scalar_one_or_none()

    async def replace_items(self, invoice_id: uuid.UUID, items: list[dict[str, Any]]) -> None:
        await self.session.execute(
            delete(InvoiceItem)
            .where(InvoiceItem.organization_id == self.organization_id)
            .where(InvoiceItem.invoice_id == invoice_id)
        )
        for position, item in enumerate(items):
            self.session.add(
                InvoiceItem(
                    organization_id=self.organization_id,
                    invoice_id=invoice_id,
                    position=position,
                    **item,
                )
            )
        await self.session.flush()

    async def listed(
        self,
        *,
        statuses: tuple[str, ...] | None,
        patient_id: uuid.UUID | None,
        typed: str | None,
        since: dt.datetime | None,
        until: dt.datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Billed], int]:
        conditions: list[Any] = [Invoice.organization_id == self.organization_id]
        if statuses:
            conditions.append(Invoice.status.in_(statuses))
        if patient_id is not None:
            conditions.append(Invoice.patient_id == patient_id)
        # A draft has not been issued, so it is placed by when it was made.
        placed = func.coalesce(Invoice.issued_at, Invoice.created_at)
        if since is not None:
            conditions.append(placed >= since)
        if until is not None:
            conditions.append(placed < until)
        if typed:
            needle = f"%{_as_typed(typed.lower())}%"
            conditions.append(
                or_(
                    func.lower(Patient.first_name + " " + Patient.last_name).like(
                        needle, escape="\\"
                    ),
                    func.lower(Patient.patient_number).like(needle, escape="\\"),
                    Patient.phone.like(needle, escape="\\"),
                    func.lower(Invoice.invoice_number).like(needle, escape="\\"),
                )
            )

        counted = (
            select(func.count())
            .select_from(Invoice)
            .join(Patient, Patient.id == Invoice.patient_id)
            .where(*conditions)
        )
        total = int((await self.session.execute(counted)).scalar_one())
        found = await self._rows(
            self._joined()
            .where(*conditions)
            .order_by(placed.desc(), Invoice.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return found, total

    async def counts(self, *, patient_id: uuid.UUID | None = None) -> dict[str, int]:
        statement = (
            select(Invoice.status, func.count())
            .where(Invoice.organization_id == self.organization_id)
            .group_by(Invoice.status)
        )
        if patient_id is not None:
            statement = statement.where(Invoice.patient_id == patient_id)
        result = await self.session.execute(statement)
        found = dict.fromkeys(billing.STATUSES, 0)
        found.update({row[0]: int(row[1]) for row in result.all()})
        return found

    async def issued_between(
        self, since: dt.datetime, until: dt.datetime
    ) -> tuple[int, Decimal]:
        result = await self.session.execute(
            select(func.count(), func.coalesce(func.sum(Invoice.total), 0))
            .where(Invoice.organization_id == self.organization_id)
            .where(Invoice.status != billing.VOID)
            .where(Invoice.issued_at >= since)
            .where(Invoice.issued_at < until)
        )
        count, billed = result.one()
        return int(count), Decimal(billed)

    async def outstanding(self, *, patient_id: uuid.UUID | None = None) -> tuple[int, Decimal]:
        statement = (
            select(func.count(), func.coalesce(func.sum(Invoice.balance), 0))
            .where(Invoice.organization_id == self.organization_id)
            .where(Invoice.status.in_(billing.OWED))
        )
        if patient_id is not None:
            statement = statement.where(Invoice.patient_id == patient_id)
        result = await self.session.execute(statement)
        count, owed = result.one()
        return int(count), Decimal(owed)

    async def billed_entries(self, entry_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        if not entry_ids:
            return set()
        result = await self.session.execute(
            select(Invoice.queue_entry_id)
            .where(Invoice.organization_id == self.organization_id)
            .where(Invoice.queue_entry_id.in_(entry_ids))
            .where(Invoice.status != billing.VOID)
        )
        return {row[0] for row in result.all()}

    async def past_lines(
        self, typed: str | None, *, limit: int
    ) -> list[tuple[str, str, Decimal, int]]:
        """What this clinic has charged for before, most often first, each at
        the price it was last charged at."""
        latest = (
            select(
                func.lower(InvoiceItem.description).label("key"),
                InvoiceItem.description,
                InvoiceItem.item_type,
                InvoiceItem.unit_price,
                func.row_number()
                .over(
                    partition_by=func.lower(InvoiceItem.description),
                    order_by=Invoice.created_at.desc(),
                )
                .label("recency"),
                func.count()
                .over(partition_by=func.lower(InvoiceItem.description))
                .label("times"),
            )
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(InvoiceItem.organization_id == self.organization_id)
            .where(Invoice.status != billing.VOID)
        )
        if typed:
            latest = latest.where(
                func.lower(InvoiceItem.description).like(
                    f"%{_as_typed(typed.lower())}%", escape="\\"
                )
            )
        ranked = latest.subquery()
        result = await self.session.execute(
            select(
                ranked.c.description, ranked.c.item_type, ranked.c.unit_price, ranked.c.times
            )
            .where(ranked.c.recency == 1)
            .order_by(ranked.c.times.desc(), ranked.c.description)
            .limit(limit)
        )
        return [(row[0], row[1], Decimal(row[2]), int(row[3])) for row in result.all()]


class PaymentRepository(TenantScopedRepository[Payment]):
    model = Payment

    async def for_invoice(self, invoice_id: uuid.UUID) -> list[tuple[Payment, str | None]]:
        result = await self.session.execute(
            select(Payment, User.first_name, User.last_name)
            .outerjoin(User, User.id == Payment.received_by_id)
            .where(Payment.organization_id == self.organization_id)
            .where(Payment.invoice_id == invoice_id)
            .order_by(Payment.received_at, Payment.id)
        )
        return [
            (row[0], f"{row[1]} {row[2]}".strip() if row[1] else None) for row in result.all()
        ]

    async def by_request(self, key: str) -> Payment | None:
        result = await self.session.execute(self.query().where(Payment.request_key == key))
        return result.scalar_one_or_none()

    async def by_method(
        self, since: dt.datetime, until: dt.datetime
    ) -> list[tuple[str, str, str, Decimal, int]]:
        result = await self.session.execute(
            select(
                Payment.method,
                Payment.kind,
                Payment.channel,
                func.sum(Payment.amount),
                func.count(),
            )
            .where(Payment.organization_id == self.organization_id)
            .where(Payment.received_at >= since)
            .where(Payment.received_at < until)
            .group_by(Payment.method, Payment.kind, Payment.channel)
        )
        return [(row[0], row[1], row[2], Decimal(row[3]), int(row[4])) for row in result.all()]


class PaymentLinkRepository(TenantScopedRepository[PaymentLink]):
    model = PaymentLink

    async def open_for_invoice(self, invoice_id: uuid.UUID) -> PaymentLink | None:
        result = await self.session.execute(
            self.query()
            .where(PaymentLink.invoice_id == invoice_id)
            .where(PaymentLink.status == billing.LINK_OPEN)
        )
        return result.scalar_one_or_none()

    async def latest_for_invoice(self, invoice_id: uuid.UUID) -> PaymentLink | None:
        result = await self.session.execute(
            self.query()
            .where(PaymentLink.invoice_id == invoice_id)
            .order_by(PaymentLink.created_at.desc(), PaymentLink.id.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def by_gateway_payment(self, payment_id: str) -> PaymentLink | None:
        result = await self.session.execute(
            self.query().where(PaymentLink.gateway_payment_id == payment_id)
        )
        return result.scalar_one_or_none()


# Whoever opens a payment link has no session and so no clinic. These two
# find the row from what the URL or the gateway carries, and the clinic comes
# off the row itself; every read after that is scoped to it as usual.


async def link_by_token(session: AsyncSession, token_hash: str) -> PaymentLink | None:
    result = await session.execute(
        select(PaymentLink).where(PaymentLink.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def link_by_order(session: AsyncSession, order_id: str) -> PaymentLink | None:
    result = await session.execute(
        select(PaymentLink)
        .where(PaymentLink.order_id == order_id)
        .order_by(PaymentLink.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()
