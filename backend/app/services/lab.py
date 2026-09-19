"""Lab orders: asked for in the room, typed in when the report comes back.

The doctor orders tests while the visit is open, one at a time, and can take
one back while the patient is still with them. Once the visit is finished an
order has gone out, so it is cancelled with a reason instead of removed.

Whoever records results types the report in when it arrives, usually the
desk, and can put a slip right until the doctor has looked at it. The
doctor who ordered the test marks it seen, and from then on it stays as it
was.

Results are part of the patient's record, so anyone at the clinic who reads
lab work reads every patient's, as with vital signs and prescriptions. A
doctor acts only on their own orders.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound, PermissionDenied, ValidationFailed
from app.models import LabOrder, LabResultValue, Organization, lab
from app.models.counter import LAB_ORDER
from app.repositories.consultations import ConsultationRepository
from app.repositories.counters import next_in_sequence
from app.repositories.lab import LabRepository, Ordered
from app.schemas.lab import MAX_PER_VISIT, LabOrderIn, LabResultIn
from app.services import lab_catalogue as catalogue
from app.services.appointments import Reach, spoken_day
from app.services.doctors import clinic_today, clinic_zone
from app.services.patients import age_in_years
from app.services.queue import doctor_ref, patient_ref


class LabOrderNotFound(NotFound):
    code = "LAB_NOT_FOUND"
    message = "That lab order could not be found."


class VisitClosed(AppError):
    code = "LAB_VISIT_CLOSED"
    status = 409
    message = "The visit is finished, so tests can no longer be ordered on it."


class AlreadyOrdered(AppError):
    code = "LAB_ALREADY_ORDERED"
    status = 409
    message = "That test is already ordered on this visit."


class NotOrderer(AppError):
    code = "LAB_NOT_ORDERER"
    status = 403
    message = "Only the doctor who ordered this test can do that."


class OrderLocked(AppError):
    code = "LAB_LOCKED"
    status = 409
    message = "This order can no longer be changed."


class Unlinked(PermissionDenied):
    message = (
        "Your account is not linked to a doctor profile yet. "
        "Ask the clinic admin to link it before ordering tests."
    )


def _number(sequence: int) -> str:
    return f"LAB-{sequence:06d}"


def _blank(value: str | None) -> str | None:
    return value if value else None


def _is_orderer(reach: Reach, order: LabOrder) -> bool:
    return reach.narrowed and reach.doctor_id == order.doctor_id


# --- The list of tests ---------------------------------------------------------


async def the_list(session: AsyncSession, *, organization_id: uuid.UUID) -> dict[str, Any]:
    """Every listed test, and after them whatever the clinic has typed in
    before, so a test it orders often is as quick to find the second time."""
    listed, typed = await LabRepository(session, organization_id).times_ordered()
    tests = [
        {
            "code": test.code,
            "name": test.name,
            "also": list(test.also),
            "category": test.category,
            "prepare": test.prepare,
            "parts": len(test.parts),
            "times_ordered": listed.get(test.code, 0),
        }
        for test in catalogue.tests()
    ]
    tests += [
        {
            "code": None,
            "name": name,
            "also": [],
            "category": category,
            "prepare": None,
            "parts": 0,
            "times_ordered": times,
        }
        for name, category, times in typed
    ]
    return {"categories": catalogue.categories(), "tests": tests}


# --- Ordering ------------------------------------------------------------------


def _which_test(body: LabOrderIn) -> tuple[str | None, str, str | None, str | None]:
    """The code, name, category and preparation of what was asked for."""
    if body.test_code:
        test = catalogue.find(body.test_code)
        if test is None:
            raise ValidationFailed({"test_code": "That test is not on the list."})
    else:
        typed = " ".join((body.test_name or "").split())
        if not typed:
            raise ValidationFailed({"test_name": "Say which test."}, "Say which test to order.")
        test = catalogue.named(typed)
        if test is None:
            return None, typed, None, None
    return test.code, test.name, test.category, test.prepare


async def order(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    body: LabOrderIn,
) -> uuid.UUID:
    if not reach.narrowed:
        raise PermissionDenied("Tests are ordered by the doctor who sees the patient.")
    if reach.doctor_id is None:
        raise Unlinked
    code, name, category, prepare = _which_test(body)

    # The visit is locked, so two tabs ordering the same test at once take
    # turns and the second finds the first's order.
    visit = await ConsultationRepository(session, organization_id).one(
        body.consultation_id, lock=True
    )
    if visit is None:
        raise ValidationFailed({"consultation_id": "Those notes could not be found."})
    if visit.doctor.id != reach.doctor_id:
        raise NotOrderer(
            f"This visit is {visit.doctor.display_name}'s. Only they can order tests for it."
        )
    if not visit.consultation.is_draft:
        raise VisitClosed

    repository = LabRepository(session, organization_id)
    already = await repository.active_for_visit(visit.consultation.id)
    if any(each.test_name.lower() == name.lower() for each in already):
        raise AlreadyOrdered(f"{name} is already ordered on this visit.")
    if len(already) >= MAX_PER_VISIT:
        raise ValidationFailed(
            {"test_name": f"That is {MAX_PER_VISIT} tests, as many as one visit takes."},
            f"That is {MAX_PER_VISIT} tests, as many as one visit takes.",
        )

    # Left out, the list's own preparation goes on; sent empty, nothing does.
    if "instructions" in body.model_fields_set:
        instructions = _blank(body.instructions)
    else:
        instructions = prepare

    sequence = await next_in_sequence(session, organization_id, LAB_ORDER)
    placed = await repository.add(
        LabOrder(
            consultation_id=visit.consultation.id,
            patient_id=visit.consultation.patient_id,
            doctor_id=visit.consultation.doctor_id,
            order_number=_number(sequence),
            test_code=code,
            test_name=name,
            category=category,
            urgent=body.urgent,
            instructions=instructions,
            status=lab.ORDERED,
            ordered_at=dt.datetime.now(dt.UTC),
            ordered_by_id=actor_id,
        )
    )
    return placed.id


async def _locked(
    session: AsyncSession, organization_id: uuid.UUID, order_id: uuid.UUID
) -> Ordered:
    """The order, locked after its visit, which is the order ordering takes
    them in, so the two never wait on each other."""
    repository = LabRepository(session, organization_id)
    found = await repository.one(order_id)
    if found is None:
        raise LabOrderNotFound
    await ConsultationRepository(session, organization_id).one(found.visit.id, lock=True)
    locked = await repository.one(order_id, lock=True)
    if locked is None:
        raise LabOrderNotFound
    return locked


def _why_not_removable(found: Ordered) -> str | None:
    if found.order.status == lab.CANCELLED:
        return "It has already been cancelled."
    if found.order.status != lab.ORDERED:
        return "It has a result now, so it stays on the record."
    if not found.visit.is_draft:
        return "The visit is finished, so the order has gone out. Cancel it instead."
    return None


async def remove(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    order_id: uuid.UUID,
) -> None:
    """Takes back a test ordered by mistake, while the patient is still in
    the room. Nothing is left behind, as nothing has been done with it."""
    found = await _locked(session, organization_id, order_id)
    if not _is_orderer(reach, found.order):
        raise NotOrderer
    why = _why_not_removable(found)
    if why is not None:
        raise OrderLocked(why)
    await session.delete(found.order)
    await session.flush()


def _may_cancel(found: Ordered, reach: Reach, *, may_create: bool, may_update: bool) -> bool:
    if not reach.covers(found.doctor.id):
        return False
    return may_update or (may_create and _is_orderer(reach, found.order))


async def cancel(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    may_create: bool,
    may_update: bool,
    actor_id: uuid.UUID,
    order_id: uuid.UUID,
    reason: str,
) -> None:
    """For a test that is not going to be done: the patient had it done
    elsewhere, or decided against it. Kept, with who called it off and why."""
    found = await _locked(session, organization_id, order_id)
    if not _may_cancel(found, reach, may_create=may_create, may_update=may_update):
        if not reach.covers(found.doctor.id):
            raise LabOrderNotFound
        raise NotOrderer("Only the doctor who ordered this test, or the desk, can cancel it.")
    order = found.order
    if order.status == lab.CANCELLED:
        raise OrderLocked("It has already been cancelled.")
    if order.status != lab.ORDERED:
        raise OrderLocked("It has a result now, so it cannot be cancelled.")
    order.status = lab.CANCELLED
    order.cancelled_at = dt.datetime.now(dt.UTC)
    order.cancelled_by_id = actor_id
    order.cancel_reason = reason
    await session.flush()


# --- Results -------------------------------------------------------------------


def _ordered_on(order: LabOrder, clinic: Organization) -> dt.date:
    return order.ordered_at.astimezone(clinic_zone(clinic)).date()


def _checked(body: LabResultIn, *, ordered_on: dt.date, today: dt.date) -> list[dict[str, Any]]:
    fields: dict[str, str] = {}
    if body.reported_on > today:
        fields["reported_on"] = "The report cannot be dated after today."
    elif body.reported_on < ordered_on:
        fields["reported_on"] = (
            f"The test was ordered on {spoken_day(ordered_on, beside=today)}, "
            "so the report cannot be dated before that."
        )

    seen: set[str] = set()
    values: list[dict[str, Any]] = []
    for index, line in enumerate(body.values):
        key = " ".join(line.name.lower().split())
        if key in seen:
            fields[f"values.{index}.name"] = f"{line.name} is already on the report."
        seen.add(key)
        if not line.value:
            fields[f"values.{index}.value"] = "Type the value, or take the line out."
        if line.low is not None and line.high is not None and line.low > line.high:
            fields[f"values.{index}.high"] = "The top of the range is below the bottom."
        values.append(
            {
                "name": line.name,
                "value": line.value,
                "unit": _blank(line.unit),
                "low": line.low,
                "high": line.high,
                "expected": _blank(line.expected),
            }
        )
    if fields:
        raise ValidationFailed(fields, next(iter(fields.values())))
    if not values and not body.findings:
        raise ValidationFailed(
            {"values": "Type in at least one value, or what the report says."},
            "Type in at least one value, or what the report says.",
        )
    return values


def _why_not_enterable(order: LabOrder) -> str | None:
    if order.status == lab.CANCELLED:
        return "This order was cancelled."
    if order.status == lab.REVIEWED:
        return "The doctor has already seen this result, so it stays as it was."
    return None


async def record(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    order_id: uuid.UUID,
    body: LabResultIn,
) -> None:
    """Types the report in, or puts right the one typed in before."""
    found = await _locked(session, organization_id, order_id)
    order = found.order
    if not reach.covers(found.doctor.id):
        raise LabOrderNotFound
    why = _why_not_enterable(order)
    if why is not None:
        raise OrderLocked(why)
    values = _checked(body, ordered_on=_ordered_on(order, clinic), today=clinic_today(clinic))

    await LabRepository(session, organization_id).replace_values(order.id, values)
    order.reported_on = body.reported_on
    order.lab_name = _blank(body.lab_name)
    order.findings = _blank(body.findings)
    if order.status == lab.ORDERED:
        order.status = lab.RESULTED
        order.resulted_at = dt.datetime.now(dt.UTC)
        order.resulted_by_id = actor_id
    else:
        order.changed_by_id = actor_id
    await session.flush()


async def clear(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    order_id: uuid.UUID,
) -> None:
    """Takes a result back off, for a report typed against the wrong order."""
    found = await _locked(session, organization_id, order_id)
    order = found.order
    if not reach.covers(found.doctor.id):
        raise LabOrderNotFound
    why = _why_not_enterable(order)
    if why is not None:
        raise OrderLocked(why)
    if order.status != lab.RESULTED:
        raise OrderLocked("There is no result on this order to take off.")
    await LabRepository(session, organization_id).replace_values(order.id, [])
    order.status = lab.ORDERED
    for column in (
        "reported_on",
        "lab_name",
        "findings",
        "resulted_at",
        "resulted_by_id",
        "changed_by_id",
    ):
        setattr(order, column, None)
    await session.flush()


async def review(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    order_id: uuid.UUID,
) -> None:
    found = await _locked(session, organization_id, order_id)
    order = found.order
    if not _is_orderer(reach, order):
        raise NotOrderer(
            f"This test was ordered by {found.doctor.display_name}. "
            "Only they can mark the result as seen."
        )
    if order.status == lab.REVIEWED:
        raise OrderLocked("You have already marked this result as seen.")
    if order.status != lab.RESULTED:
        raise OrderLocked("There is no result to look at yet.")
    order.status = lab.REVIEWED
    order.reviewed_at = dt.datetime.now(dt.UTC)
    order.reviewed_by_id = actor_id
    await session.flush()


# --- Reading -------------------------------------------------------------------


def _flag(value: LabResultValue) -> str | None:
    return catalogue.judge(value.value, low=value.low, high=value.high, expected=value.expected)


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def flagged(values: list[LabResultValue]) -> int:
    return sum(1 for value in values if _flag(value))


def _value(value: LabResultValue) -> dict[str, Any]:
    return {
        "name": value.name,
        "value": value.value,
        "unit": value.unit,
        "low": _float(value.low),
        "high": _float(value.high),
        "expected": value.expected,
        "flag": _flag(value),
    }


def _brief(found: Ordered) -> dict[str, Any]:
    order = found.order
    return {
        "id": order.id,
        "order_number": order.order_number,
        "test_code": order.test_code,
        "test_name": order.test_name,
        "category": order.category,
        "urgent": order.urgent,
        "instructions": order.instructions,
        "status": order.status,
        "ordered_at": order.ordered_at,
        "reported_on": order.reported_on,
        "flagged": flagged(found.values),
        "consultation_id": order.consultation_id,
    }


def _listed(found: Ordered, today: dt.date) -> dict[str, Any]:
    return {
        **_brief(found),
        "patient": patient_ref(found.patient, found.allergy_count, today),
        "doctor": doctor_ref(found.doctor),
    }


def _earlier(found: Ordered, before: Ordered | None) -> dict[str, dict[str, Any]]:
    """Each value on the last report, by name, where it was measured the
    same way. A value in other units is not set beside this one, since the
    two numbers would not mean the same thing."""
    if before is None or before.order.reported_on is None:
        return {}
    kept = {}
    for value in before.values:
        kept[" ".join(value.name.lower().split())] = value
    matched = {}
    for value in found.values:
        key = " ".join(value.name.lower().split())
        earlier = kept.get(key)
        if earlier is None or (earlier.unit or "") != (value.unit or ""):
            continue
        matched[key] = {
            "value": earlier.value,
            "flag": _flag(earlier),
            "reported_on": before.order.reported_on,
        }
    return matched


async def detail(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    may_create: bool,
    may_update: bool,
    order_id: uuid.UUID,
) -> dict[str, Any]:
    repository = LabRepository(session, organization_id)
    found = await repository.one(order_id)
    if found is None:
        raise LabOrderNotFound
    order, today = found.order, clinic_today(clinic)

    earlier = _earlier(found, await repository.earlier_report(found))
    listed_test = catalogue.find(order.test_code) if order.test_code else None
    template, left_out = (
        catalogue.template(
            listed_test,
            gender=found.patient.gender,
            age=age_in_years(found.patient.date_of_birth, today),
        )
        if listed_test
        else ([], False)
    )
    covered = reach.covers(found.doctor.id)
    removable = _is_orderer(reach, order) and may_create and _why_not_removable(found) is None
    people = found.people

    return {
        **_listed(found, today),
        "ordered_by": people.get("ordered_by"),
        "cancelled_at": order.cancelled_at,
        "cancelled_by": people.get("cancelled_by"),
        "cancel_reason": order.cancel_reason,
        "lab_name": order.lab_name,
        "findings": order.findings,
        "values": [
            {**_value(value), "earlier": earlier.get(" ".join(value.name.lower().split()))}
            for value in found.values
        ],
        "resulted_at": order.resulted_at,
        "resulted_by": people.get("resulted_by"),
        "changed_by": people.get("changed_by"),
        "reviewed_at": order.reviewed_at,
        "reviewed_by": people.get("reviewed_by"),
        "template": template,
        "ranges_left_out": left_out,
        "visit_date": found.visit.started_at.astimezone(clinic_zone(clinic)).date(),
        "visit_open": found.visit.is_draft,
        "can_enter": may_update and covered and _why_not_enterable(order) is None,
        "can_review": may_create and _is_orderer(reach, order) and order.status == lab.RESULTED,
        "can_cancel": order.status == lab.ORDERED
        and not removable
        and _may_cancel(found, reach, may_create=may_create, may_update=may_update),
        "can_remove": removable,
    }


STATUS_GROUPS: dict[str, tuple[str, ...]] = {
    "waiting": (lab.ORDERED,),
    "to_review": (lab.RESULTED,),
    "reviewed": (lab.REVIEWED,),
    "cancelled": (lab.CANCELLED,),
    "open": lab.OPEN,
}


async def listed(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    patient_id: uuid.UUID | None,
    consultation_id: uuid.UUID | None,
    doctor_id: uuid.UUID | None,
    show: str | None,
    typed: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    repository = LabRepository(session, organization_id)
    found, total = await repository.listed(
        patient_id=patient_id,
        consultation_id=consultation_id,
        doctor_id=doctor_id,
        statuses=STATUS_GROUPS[show] if show else None,
        typed=typed,
        limit=limit,
        offset=offset,
    )
    today = clinic_today(clinic)
    return {
        "items": [_listed(each, today) for each in found],
        "total": total,
        "counts": await repository.counts(doctor_id=doctor_id),
    }
