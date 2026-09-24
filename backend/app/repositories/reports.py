"""Counts and sums over a stretch of days.

Everything here reads; nothing writes. The queries group in the database
rather than pulling rows back to be added up in Python, because a busy
clinic asked for a year at a time would otherwise carry tens of thousands
of payments across the wire to produce twelve numbers.

Dates are the clinic's own. A queue entry already carries the clinic's date
on it, so visits group by that column directly. Money carries an instant
instead, and an instant has to be turned into the clinic's date before it
can be grouped by day: a payment taken at half past eleven at night in
Kolkata belongs to that evening's takings, not to the next morning's.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Doctor,
    Invoice,
    InvoiceItem,
    LabOrder,
    Patient,
    Payment,
    QueueEntry,
    billing,
    lab,
)
from app.models import queue as line

# How many of each list the page shows. Past this the answer stops being
# something anybody reads and starts being a spreadsheet.
TOP = 8


def _local_date(zone: str, column: Any) -> Any:
    """The clinic's calendar date for an instant stored against UTC."""
    return func.date(func.timezone(zone, column))


class ReportsRepository:
    """Deliberately not one of the model-scoped repositories: these queries
    span bills, visits and lab orders together. Each one filters on the
    organisation itself, which is the price of reaching across tables.
    """

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    # --- Visits -------------------------------------------------------------------

    def _days(
        self, first: dt.date, last: dt.date, doctor_id: uuid.UUID | None
    ) -> list[ColumnElement[bool]]:
        where: list[ColumnElement[bool]] = [
            QueueEntry.organization_id == self.organization_id,
            QueueEntry.token_date >= first,
            QueueEntry.token_date <= last,
        ]
        if doctor_id is not None:
            where.append(QueueEntry.doctor_id == doctor_id)
        return where

    async def visits_by_day(
        self, first: dt.date, last: dt.date, *, doctor_id: uuid.UUID | None
    ) -> list[tuple[dt.date, int, int, int]]:
        """Each day anybody came: seen, how many of those walked in, and the
        ones who never stayed to be seen."""
        seen = QueueEntry.status == line.COMPLETED
        result = await self.session.execute(
            select(
                QueueEntry.token_date,
                func.count().filter(seen),
                func.count().filter(seen, QueueEntry.appointment_id.is_(None)),
                func.count().filter(QueueEntry.status == line.NO_SHOW),
            )
            .where(*self._days(first, last, doctor_id))
            .group_by(QueueEntry.token_date)
            .order_by(QueueEntry.token_date)
        )
        return [(row[0], int(row[1]), int(row[2]), int(row[3])) for row in result.all()]

    async def seen_by_hour(
        self, first: dt.date, last: dt.date, *, zone: str, doctor_id: uuid.UUID | None
    ) -> list[tuple[int, int]]:
        """What time of day people arrive, by the clinic's clock."""
        hour = func.extract("hour", func.timezone(zone, QueueEntry.checked_in_at))
        result = await self.session.execute(
            select(hour, func.count())
            .where(*self._days(first, last, doctor_id))
            .group_by(hour)
            .order_by(hour)
        )
        return [(int(row[0]), int(row[1])) for row in result.all()]

    async def by_doctor(
        self, first: dt.date, last: dt.date, *, doctor_id: uuid.UUID | None
    ) -> list[tuple[Doctor, int, int, int | None]]:
        """Every doctor who had a line: seen, never stayed, and how long a
        visit took them on average."""
        seen = QueueEntry.status == line.COMPLETED
        minutes = func.avg(
            func.extract("epoch", QueueEntry.completed_at - QueueEntry.started_at) / 60
        ).filter(seen, QueueEntry.started_at.is_not(None), QueueEntry.completed_at.is_not(None))
        result = await self.session.execute(
            select(
                Doctor,
                func.count().filter(seen),
                func.count().filter(QueueEntry.status == line.NO_SHOW),
                minutes,
            )
            .join(QueueEntry, QueueEntry.doctor_id == Doctor.id)
            .where(*self._days(first, last, doctor_id))
            .group_by(Doctor.id)
        )
        return [
            (row[0], int(row[1]), int(row[2]), None if row[3] is None else round(float(row[3])))
            for row in result.all()
        ]

    async def registered_by_day(
        self, since: dt.datetime, until: dt.datetime, *, zone: str
    ) -> list[tuple[dt.date, int]]:
        """Patients whose record was opened on each day."""
        day = _local_date(zone, Patient.created_at)
        result = await self.session.execute(
            select(day, func.count())
            .where(Patient.organization_id == self.organization_id)
            .where(Patient.created_at >= since)
            .where(Patient.created_at < until)
            .group_by(day)
            .order_by(day)
        )
        return [(row[0], int(row[1])) for row in result.all()]

    # --- Money --------------------------------------------------------------------

    def _taken(self, since: dt.datetime, until: dt.datetime) -> list[ColumnElement[bool]]:
        return [
            Payment.organization_id == self.organization_id,
            Payment.received_at >= since,
            Payment.received_at < until,
        ]

    def _theirs(self, statement: Select[Any], doctor_id: uuid.UUID | None) -> Select[Any]:
        """Narrowed to the money taken against one doctor's bills."""
        if doctor_id is None:
            return statement
        return statement.join(Invoice, Invoice.id == Payment.invoice_id).where(
            Invoice.doctor_id == doctor_id
        )

    async def by_method(
        self, since: dt.datetime, until: dt.datetime, *, doctor_id: uuid.UUID | None = None
    ) -> list[tuple[str, str, str, Decimal, int]]:
        """Method, whether it came in or went back, over the desk or from a
        link, the sum and how many."""
        result = await self.session.execute(
            self._theirs(
                select(
                    Payment.method,
                    Payment.kind,
                    Payment.channel,
                    func.sum(Payment.amount),
                    func.count(),
                ).where(*self._taken(since, until)),
                doctor_id,
            ).group_by(Payment.method, Payment.kind, Payment.channel)
        )
        return [(row[0], row[1], row[2], Decimal(row[3]), int(row[4])) for row in result.all()]

    async def money_by_day(
        self,
        since: dt.datetime,
        until: dt.datetime,
        *,
        zone: str,
        doctor_id: uuid.UUID | None,
    ) -> list[tuple[dt.date, Decimal, Decimal]]:
        """Each day's takings, and what went back out of them."""
        day = _local_date(zone, Payment.received_at)
        came_in = func.coalesce(
            func.sum(Payment.amount).filter(Payment.kind == billing.PAYMENT), 0
        )
        went_back = func.coalesce(
            func.sum(Payment.amount).filter(Payment.kind == billing.REFUND), 0
        )
        result = await self.session.execute(
            self._theirs(
                select(day, came_in, went_back).where(*self._taken(since, until)), doctor_id
            )
            .group_by(day)
            .order_by(day)
        )
        return [(row[0], Decimal(row[1]), Decimal(row[2])) for row in result.all()]

    async def billed_by_doctor(
        self, since: dt.datetime, until: dt.datetime
    ) -> dict[uuid.UUID, Decimal]:
        """What each doctor's bills came to, by the day they were handed over."""
        result = await self.session.execute(
            select(Invoice.doctor_id, func.coalesce(func.sum(Invoice.total), 0))
            .where(Invoice.organization_id == self.organization_id)
            .where(Invoice.status != billing.VOID)
            .where(Invoice.doctor_id.is_not(None))
            .where(Invoice.issued_at >= since)
            .where(Invoice.issued_at < until)
            .group_by(Invoice.doctor_id)
        )
        return {row[0]: Decimal(row[1]) for row in result.all()}

    async def collected_by_doctor(
        self, since: dt.datetime, until: dt.datetime
    ) -> dict[uuid.UUID, Decimal]:
        """Money that came in against each doctor's bills, less anything
        given back out of it."""
        came_in = func.coalesce(
            func.sum(Payment.amount).filter(Payment.kind == billing.PAYMENT), 0
        ) - func.coalesce(func.sum(Payment.amount).filter(Payment.kind == billing.REFUND), 0)
        result = await self.session.execute(
            select(Invoice.doctor_id, came_in)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(*self._taken(since, until))
            .where(Invoice.doctor_id.is_not(None))
            .group_by(Invoice.doctor_id)
        )
        return {row[0]: Decimal(row[1]) for row in result.all()}

    async def issued(
        self, since: dt.datetime, until: dt.datetime, *, doctor_id: uuid.UUID | None
    ) -> tuple[int, Decimal]:
        """Bills handed over in this stretch, and what they came to."""
        statement = (
            select(func.count(), func.coalesce(func.sum(Invoice.total), 0))
            .where(Invoice.organization_id == self.organization_id)
            .where(Invoice.status != billing.VOID)
            .where(Invoice.issued_at >= since)
            .where(Invoice.issued_at < until)
        )
        if doctor_id is not None:
            statement = statement.where(Invoice.doctor_id == doctor_id)
        result = await self.session.execute(statement)
        count, billed = result.one()
        return int(count), Decimal(billed)

    async def owed(self, *, doctor_id: uuid.UUID | None) -> tuple[int, Decimal]:
        """Still unpaid on issued bills, whenever they were raised.

        This one ignores the dates asked for on purpose: money owed since
        March is still owed in September, and a figure that forgot it would
        be worse than no figure to whoever is chasing it.
        """
        statement = (
            select(func.count(), func.coalesce(func.sum(Invoice.balance), 0))
            .where(Invoice.organization_id == self.organization_id)
            .where(Invoice.status.in_(billing.OWED))
        )
        if doctor_id is not None:
            statement = statement.where(Invoice.doctor_id == doctor_id)
        result = await self.session.execute(statement)
        count, balance = result.one()
        return int(count), Decimal(balance)

    # --- What was ordered and charged for -----------------------------------------

    async def tests_ordered(
        self, since: dt.datetime, until: dt.datetime, *, doctor_id: uuid.UUID | None
    ) -> list[tuple[str, int]]:
        """The tests asked for most, by the name they were ordered under."""
        statement = (
            select(LabOrder.test_name, func.count())
            .where(LabOrder.organization_id == self.organization_id)
            .where(LabOrder.status != lab.CANCELLED)
            .where(LabOrder.ordered_at >= since)
            .where(LabOrder.ordered_at < until)
            .group_by(LabOrder.test_name)
            .order_by(func.count().desc(), LabOrder.test_name)
            .limit(TOP)
        )
        if doctor_id is not None:
            statement = statement.where(LabOrder.doctor_id == doctor_id)
        result = await self.session.execute(statement)
        return [(row[0], int(row[1])) for row in result.all()]

    async def charged_for(
        self, since: dt.datetime, until: dt.datetime, *, doctor_id: uuid.UUID | None
    ) -> list[tuple[str, int, Decimal]]:
        """What the clinic charged for most, biggest earner first.

        Grouped by the wording folded to lower case, so two desks typing
        "Consultation" and "consultation" are charging for one thing.
        """
        key = func.lower(InvoiceItem.description)
        statement = (
            select(
                func.min(InvoiceItem.description),
                func.sum(InvoiceItem.quantity),
                func.sum(InvoiceItem.amount),
            )
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(InvoiceItem.organization_id == self.organization_id)
            .where(Invoice.status != billing.VOID)
            .where(Invoice.issued_at >= since)
            .where(Invoice.issued_at < until)
            .group_by(key)
            .order_by(func.sum(InvoiceItem.amount).desc(), key)
            .limit(TOP)
        )
        if doctor_id is not None:
            statement = statement.where(Invoice.doctor_id == doctor_id)
        result = await self.session.execute(statement)
        return [(row[0], int(row[1]), Decimal(row[2])) for row in result.all()]

    async def payments_in(
        self, since: dt.datetime, until: dt.datetime, *, doctor_id: uuid.UUID | None
    ) -> list[tuple[Payment, Invoice, Patient, Doctor | None]]:
        """Every payment and refund in the stretch, oldest first, with the
        bill it belongs to. For the file the clinic hands its accountant."""
        statement = (
            select(Payment, Invoice, Patient, Doctor)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .join(Patient, Patient.id == Invoice.patient_id)
            .outerjoin(Doctor, Doctor.id == Invoice.doctor_id)
            .where(*self._taken(since, until))
            .order_by(Payment.received_at)
        )
        if doctor_id is not None:
            statement = statement.where(Invoice.doctor_id == doctor_id)
        result = await self.session.execute(statement)
        return [(row[0], row[1], row[2], row[3]) for row in result.all()]
