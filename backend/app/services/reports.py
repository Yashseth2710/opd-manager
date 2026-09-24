"""What the clinic did over a stretch of days.

One place works the figures out, and three screens read them: the day's
takings on the billing page, the money line on the first page after signing
in, and the reports page itself. They agreed by accident before and would
have drifted the first time one of them grew a filter the others did not.

A doctor with permission to read reports sees their own work rather than
the clinic's: their patients, their bills, their tests. The narrowing is the
same one the day's queue uses, so the two pages cannot disagree about whose
patients are whose.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationFailed
from app.models import Organization, billing
from app.repositories.reports import ReportsRepository
from app.services.appointments import Reach
from app.services.doctors import at_clinic, clinic_today, clinic_zone
from app.services.queue import doctor_ref

ZERO = Decimal("0.00")

# A year and a day. Past that the page stops being readable long before the
# query stops being cheap, and nobody asks a clinic dashboard for a decade.
LONGEST = 366

TODAY = "today"
WEEK = "week"
MONTH = "month"
THIS_MONTH = "this_month"
LAST_MONTH = "last_month"
CUSTOM = "custom"
RANGES = (TODAY, WEEK, MONTH, THIS_MONTH, LAST_MONTH, CUSTOM)

LABELS = {
    TODAY: "Today",
    WEEK: "Last 7 days",
    MONTH: "Last 30 days",
    THIS_MONTH: "This month",
    LAST_MONTH: "Last month",
    CUSTOM: "Chosen dates",
}


def _zone_name(clinic: Organization) -> str:
    """The clinic's timezone, as a name Postgres will accept.

    The database does the grouping by day, so a clinic carrying a zone this
    installation has never heard of has to fall back before the query is
    built rather than after it fails.
    """
    named = clinic.timezone or "UTC"
    return named if str(clinic_zone(clinic)) == named else "UTC"


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _first_of(day: dt.date) -> dt.date:
    return day.replace(day=1)


def span_for(
    clinic: Organization, chosen: str, first: dt.date | None, last: dt.date | None
) -> dict[str, Any]:
    """The days a request is asking about, worked out at the clinic.

    Anything the caller does not pin down comes from the clinic's own today,
    so a request sent at five past midnight in London still asks a Kolkata
    clinic about the day it is having.
    """
    today = clinic_today(clinic)
    if chosen == TODAY:
        first = last = today
    elif chosen == WEEK:
        first, last = today - dt.timedelta(days=6), today
    elif chosen == MONTH:
        first, last = today - dt.timedelta(days=29), today
    elif chosen == THIS_MONTH:
        first, last = _first_of(today), today
    elif chosen == LAST_MONTH:
        last = _first_of(today) - dt.timedelta(days=1)
        first = _first_of(last)
    elif first is None or last is None:
        raise ValidationFailed(
            {"from": "Give a first and a last day."},
            "Choose both a first day and a last day.",
        )
    elif last < first:
        raise ValidationFailed(
            {"to": "This is before the day you started from."},
            "The last day comes before the first one.",
        )
    elif (last - first).days + 1 > LONGEST:
        raise ValidationFailed(
            {"to": "A year at a time is the most this can show."},
            "That is more than a year. Ask for a shorter stretch.",
        )
    else:
        chosen = CUSTOM

    return {
        "range": chosen,
        "first_day": first,
        "last_day": last,
        "days": (last - first).days + 1,
        "label": LABELS[chosen],
    }


def _bounds(
    clinic: Organization, first: dt.date, last: dt.date
) -> tuple[dt.datetime, dt.datetime]:
    """Midnight at the start of the first day to midnight after the last,
    both at the clinic rather than wherever the server happens to be."""
    return (
        at_clinic(clinic, first, dt.time()),
        at_clinic(clinic, last + dt.timedelta(days=1), dt.time()),
    )


async def takings(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    since: dt.datetime,
    until: dt.datetime,
    doctor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The money side, whatever stretch of time is asked for.

    Shared by the day's takings on the billing page and by the reports page,
    so a day looked at from either place reports the same figures.
    """
    reports = ReportsRepository(session, organization_id)
    rows = await reports.by_method(since, until, doctor_id=doctor_id)

    methods: dict[str, dict[str, Any]] = {}
    online = ZERO
    for method, kind, channel, amount, count in rows:
        entry = methods.setdefault(
            method,
            {"method": method, "received": ZERO, "refunded": ZERO, "net": ZERO, "count": 0},
        )
        if kind == billing.REFUND:
            entry["refunded"] += amount
        else:
            entry["received"] += amount
            entry["count"] += count
            if channel == billing.ONLINE:
                online += amount
        entry["net"] = entry["received"] - entry["refunded"]
    ordered = [methods[method] for method in billing.METHODS if method in methods]

    issued_count, billed = await reports.issued(since, until, doctor_id=doctor_id)
    owed_count, owed = await reports.owed(doctor_id=doctor_id)
    received = sum((each["received"] for each in ordered), ZERO)
    refunded = sum((each["refunded"] for each in ordered), ZERO)
    return {
        "methods": ordered,
        "received": received,
        "refunded": refunded,
        "net": received - refunded,
        # Of what came in, the part nobody at the desk had to handle.
        "online": online,
        "bills_issued": issued_count,
        "billed": billed,
        "outstanding": owed,
        "outstanding_bills": owed_count,
    }


async def _totals(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    first: dt.date,
    last: dt.date,
    doctor_id: uuid.UUID | None,
) -> tuple[int, Decimal]:
    """Seen and collected, for the stretch just before the one asked about."""
    since, until = _bounds(clinic, first, last)
    reports = ReportsRepository(session, organization_id)
    days = await reports.visits_by_day(first, last, doctor_id=doctor_id)
    money = await reports.money_by_day(
        since, until, zone=_zone_name(clinic), doctor_id=doctor_id
    )
    seen = sum(row[1] for row in days)
    collected = sum((row[1] - row[2] for row in money), ZERO)
    return seen, collected


async def over(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    span: dict[str, Any],
) -> dict[str, Any]:
    """Everything the reports page shows, for one stretch of days."""
    first: dt.date = span["first_day"]
    last: dt.date = span["last_day"]
    shape: dict[str, Any] = {
        "span": span,
        "view": "unlinked" if reach.unlinked else "doctor" if reach.narrowed else "clinic",
        "doctor": None,
        "currency": clinic.currency,
        "seen": 0,
        "walk_ins": 0,
        "no_shows": 0,
        "new_patients": 0,
        "per_patient": ZERO,
        "before": {"seen": 0, "collected": ZERO},
        "methods": [],
        "received": ZERO,
        "refunded": ZERO,
        "net": ZERO,
        "online": ZERO,
        "bills_issued": 0,
        "billed": ZERO,
        "outstanding": ZERO,
        "outstanding_bills": 0,
        "days": [],
        "doctors": [],
        "hours": [],
        "tests": [],
        "charges": [],
    }
    if reach.unlinked:
        return shape

    doctor_id = reach.doctor_id if reach.narrowed else None
    zone = _zone_name(clinic)
    since, until = _bounds(clinic, first, last)
    reports = ReportsRepository(session, organization_id)

    visits = {
        row[0]: row for row in await reports.visits_by_day(first, last, doctor_id=doctor_id)
    }
    money = {
        row[0]: row
        for row in await reports.money_by_day(since, until, zone=zone, doctor_id=doctor_id)
    }
    # A doctor's own page does not count the clinic's new registrations as
    # theirs; nobody registers a patient to one doctor.
    registered = (
        {}
        if doctor_id is not None
        else {
            row[0]: row[1] for row in await reports.registered_by_day(since, until, zone=zone)
        }
    )

    # Every day in the stretch, including the ones nothing happened on. A
    # chart that quietly skips the empty days tells the opposite story.
    days = []
    for offset in range((last - first).days + 1):
        day = first + dt.timedelta(days=offset)
        seen, walk_ins, no_shows = visits[day][1:] if day in visits else (0, 0, 0)
        came_in, went_back = money[day][1:] if day in money else (ZERO, ZERO)
        days.append(
            {
                "date": day,
                "seen": seen,
                "walk_ins": walk_ins,
                "no_shows": no_shows,
                "registered": registered.get(day, 0),
                "collected": _money(came_in - went_back),
            }
        )
    shape["days"] = days
    shape["seen"] = sum(day["seen"] for day in days)
    shape["walk_ins"] = sum(day["walk_ins"] for day in days)
    shape["no_shows"] = sum(day["no_shows"] for day in days)
    shape["new_patients"] = sum(day["registered"] for day in days)

    shape.update(
        await takings(
            session,
            organization_id=organization_id,
            since=since,
            until=until,
            doctor_id=doctor_id,
        )
    )
    shape["per_patient"] = _money(shape["net"] / shape["seen"]) if shape["seen"] else ZERO

    length = dt.timedelta(days=(last - first).days + 1)
    was_seen, was_collected = await _totals(
        session,
        organization_id=organization_id,
        clinic=clinic,
        first=first - length,
        last=last - length,
        doctor_id=doctor_id,
    )
    shape["before"] = {"seen": was_seen, "collected": _money(was_collected)}

    billed = await reports.billed_by_doctor(since, until)
    collected = await reports.collected_by_doctor(since, until)
    lines: list[dict[str, Any]] = []
    for doctor, seen, no_shows, minutes in await reports.by_doctor(
        first, last, doctor_id=doctor_id
    ):
        lines.append(
            {
                "doctor": doctor_ref(doctor),
                "seen": seen,
                "no_shows": no_shows,
                "average_minutes": minutes,
                "billed": _money(billed.get(doctor.id, ZERO)),
                "collected": _money(collected.get(doctor.id, ZERO)),
            }
        )
        if doctor_id is not None and doctor.id == doctor_id:
            shape["doctor"] = doctor_ref(doctor)
    # Busiest first; a list ordered by name tells nobody anything.
    lines.sort(key=lambda each: (-int(each["seen"]), str(each["doctor"]["display_name"])))
    shape["doctors"] = lines

    shape["hours"] = [
        {"hour": hour, "seen": count}
        for hour, count in await reports.seen_by_hour(
            first, last, zone=zone, doctor_id=doctor_id
        )
    ]
    shape["tests"] = [
        {"name": name, "times": times}
        for name, times in await reports.tests_ordered(since, until, doctor_id=doctor_id)
    ]
    shape["charges"] = [
        {"description": description, "times": times, "amount": _money(amount)}
        for description, times, amount in await reports.charged_for(
            since, until, doctor_id=doctor_id
        )
    ]
    return shape


# A cell a spreadsheet would run rather than show. Excel and Sheets both
# treat a leading =, +, - or @ as the start of a formula, and a patient
# called "=cmd" is a patient, not an instruction.
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: str | None) -> str:
    text = (value or "").strip()
    return f"'{text}" if text.startswith(_FORMULA) else text


async def day_book(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    span: dict[str, Any],
) -> str:
    """Every payment and refund in the stretch, as a file to open in a
    spreadsheet. The same rows the money figures are worked out from, so a
    total on the page can be checked against the lines that make it up."""
    if reach.unlinked:
        return ""
    since, until = _bounds(clinic, span["first_day"], span["last_day"])
    zone = clinic_zone(clinic)
    rows = await ReportsRepository(session, organization_id).payments_in(
        since, until, doctor_id=reach.doctor_id if reach.narrowed else None
    )

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "Date",
            "Time",
            "Bill",
            "Patient",
            "Doctor",
            "In or out",
            "Method",
            "Taken",
            "Amount",
            "Reference",
        ]
    )
    for payment, invoice, patient, doctor in rows:
        when = payment.received_at.astimezone(zone)
        writer.writerow(
            [
                when.date().isoformat(),
                when.strftime("%H:%M"),
                _cell(invoice.invoice_number),
                _cell(f"{patient.first_name} {patient.last_name}"),
                _cell(doctor.display_name if doctor else ""),
                "Refund" if payment.kind == billing.REFUND else "Payment",
                payment.method,
                payment.channel,
                f"{payment.amount:.2f}",
                _cell(payment.reference),
            ]
        )
    return out.getvalue()
