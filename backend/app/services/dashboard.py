"""The day at a glance, for whoever has just signed in.

Built from the same queue the desk works from, so the numbers here and the
lines on the queue page never disagree. A doctor sees their own day: their
line, their next patient, the notes they have not finished, the lab reports
back for them to look at, and the patients they asked back. Everyone else sees the clinic's.

Nothing here is stored. It is worked out on each request, and the page asks
again every half a minute while it is open.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, Organization, QueueEntry
from app.models import appointment as booked
from app.models import consultation as notes
from app.models import queue as line
from app.repositories.appointments import AppointmentRepository
from app.repositories.consultations import ConsultationRepository
from app.repositories.lab import LabRepository
from app.services import lab, queue
from app.services.appointments import Reach
from app.services.doctors import clinic_now, clinic_zone, day_bounds

# Enough to act on from the first page, with the queue a click away for the rest.
SHOWN = 8


def _minutes_since(moment: dt.datetime | None, now: dt.datetime) -> int:
    if moment is None:
        return 0
    return max(0, int((now - moment).total_seconds() // 60))


def _in_room(
    entry: dict[str, Any] | None, since: str, now: dt.datetime
) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "entry_id": entry["id"],
        "token": entry["token"],
        "patient": entry["patient"],
        "minutes": _minutes_since(entry[since], now),
        "consultation_id": entry["consultation_id"],
    }


def _waiting(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": entry["id"],
        "token": entry["token"],
        "patient": entry["patient"],
        "doctor": entry["doctor"],
        "priority": entry["priority"],
        "reason": entry["appointment"]["reason"] if entry["appointment"] else entry["reason"],
        "waited_minutes": entry["waited_minutes"],
        "vitals": entry["vitals"],
    }


async def _where_they_are(
    session: AsyncSession,
    organization_id: uuid.UUID,
    clinic: Organization,
    today: dt.date,
    patient_ids: set[uuid.UUID],
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, dt.time]]:
    """Whether each of these patients is at the clinic today, has been seen,
    or is booked for later, with anyone at all rather than only the doctor
    who asked them back."""
    if not patient_ids:
        return {}, {}
    placed = await session.execute(
        select(QueueEntry.patient_id, QueueEntry.status)
        .where(QueueEntry.organization_id == organization_id)
        .where(QueueEntry.token_date == today)
        .where(QueueEntry.patient_id.in_(patient_ids))
    )
    here: dict[uuid.UUID, str] = {}
    for patient_id, status in placed.all():
        # In the building now says more than having been seen earlier today.
        if status in line.LIVE:
            here[patient_id] = "here"
        elif status == line.COMPLETED:
            here.setdefault(patient_id, "seen")

    opens_at, closes_at = day_bounds(clinic, today)
    zone = clinic_zone(clinic)
    appointments = await session.execute(
        select(Appointment.patient_id, Appointment.scheduled_start)
        .where(Appointment.organization_id == organization_id)
        .where(Appointment.patient_id.in_(patient_ids))
        .where(Appointment.scheduled_start >= opens_at)
        .where(Appointment.scheduled_start < closes_at)
        .where(Appointment.status.in_(booked.OPEN))
        .order_by(Appointment.scheduled_start)
    )
    booked_for: dict[uuid.UUID, dt.time] = {}
    for patient_id, start in appointments.all():
        booked_for.setdefault(patient_id, start.astimezone(zone).time())
    return here, booked_for


async def today(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
) -> dict[str, Any]:
    day = await queue.day(session, organization_id=organization_id, clinic=clinic, reach=reach)
    date: dt.date = day["date"]
    shape: dict[str, Any] = {
        "date": date,
        "day_name": day["day_name"],
        "view": "unlinked" if reach.unlinked else "doctor" if reach.narrowed else "clinic",
        "counts": dict.fromkeys(
            (
                "booked",
                "to_come",
                "late",
                "walk_ins",
                "waiting",
                "with_doctor",
                "seen",
                "no_shows",
            ),
            0,
        ),
        "lanes": [],
        "waiting": [],
        "waiting_total": 0,
        "without_vitals": 0,
        "arrivals": [],
        "arrivals_total": 0,
        "due_back": [],
        "unfinished": [],
        "unfinished_total": 0,
        "results": [],
        "results_total": 0,
    }
    if reach.unlinked:
        return shape

    only = reach.doctor_id if reach.narrowed else None
    now = clinic_now(clinic)
    lanes: list[dict[str, Any]] = day["lanes"]

    waiting: list[dict[str, Any]] = []
    arrivals: list[dict[str, Any]] = []
    walk_ins = gone_walking_in = 0
    for lane in lanes:
        present = [*lane["waiting"], *([lane["called"]] if lane["called"] else [])]
        waiting.extend(present)
        arrivals.extend({**arrival, "doctor": lane["doctor"]} for arrival in lane["expected"])
        walk_ins += sum(
            1
            for entry in lane["done"]
            if entry["appointment"] is None and entry["status"] == line.COMPLETED
        )
        gone_walking_in += sum(
            1
            for entry in lane["done"]
            if entry["appointment"] is None and entry["status"] == line.NO_SHOW
        )
        shape["lanes"].append(
            {
                "doctor": lane["doctor"],
                "closed": lane["closed"],
                "now_seeing": _in_room(lane["now_seeing"], "started_at", now),
                "called": _in_room(lane["called"], "called_at", now),
                "waiting": len(present) + len(lane["skipped"]),
                "longest_wait_minutes": max(
                    (entry["waited_minutes"] for entry in present), default=None
                ),
                "seen": lane["seen_count"],
                "to_come": len(lane["expected"]),
                "average_minutes": lane["average_minutes"],
                "next": _waiting(lane["called"] or lane["waiting"][0])
                if lane["called"] or lane["waiting"]
                else None,
            }
        )

    opens_at, closes_at = day_bounds(clinic, date)
    appointments = await AppointmentRepository(session, organization_id).between(
        opens_at, closes_at, doctor_id=only
    )
    statuses = [row.appointment.status for row in appointments]
    counts = shape["counts"]
    counts["booked"] = sum(1 for status in statuses if status != booked.CANCELLED)
    counts["to_come"] = len(arrivals)
    counts["late"] = sum(1 for arrival in arrivals if arrival["is_late"])
    counts["walk_ins"] = walk_ins
    counts["waiting"] = sum(lane["waiting"] for lane in shape["lanes"])
    counts["with_doctor"] = sum(1 for lane in lanes if lane["now_seeing"])
    counts["seen"] = sum(lane["seen_count"] for lane in lanes)
    counts["no_shows"] = (
        sum(1 for status in statuses if status == booked.NO_SHOW) + gone_walking_in
    )

    # Urgent first, as the line itself runs, then whoever has waited longest.
    waiting.sort(key=lambda entry: (entry["priority"] != "urgent", -entry["waited_minutes"]))
    shape["waiting"] = [_waiting(entry) for entry in waiting[:SHOWN]]
    shape["waiting_total"] = len(waiting)
    shape["without_vitals"] = sum(1 for entry in waiting if entry["vitals"] is None)

    arrivals.sort(key=lambda arrival: (arrival["start_time"], arrival["patient"]["full_name"]))
    shape["arrivals"] = [
        {
            "appointment_id": arrival["id"],
            "patient": arrival["patient"],
            "doctor": arrival["doctor"],
            "start_time": arrival["start_time"],
            "is_late": arrival["is_late"],
        }
        for arrival in arrivals[:SHOWN]
    ]
    shape["arrivals_total"] = len(arrivals)

    consultations = ConsultationRepository(session, organization_id)
    asked = await consultations.due_back(date, day_starts=opens_at, doctor_id=only)
    # One line a patient, from the latest visit that asked them back.
    latest: dict[uuid.UUID, Any] = {}
    for written in asked:
        latest.setdefault(written.patient.id, written)
    here, booked_for = await _where_they_are(
        session, organization_id, clinic, date, set(latest)
    )
    order = {"not_booked": 0, "booked": 1, "here": 2, "seen": 3}
    zone = clinic_zone(clinic)
    due_back = []
    for patient_id, written in latest.items():
        state = here.get(patient_id) or ("booked" if patient_id in booked_for else "not_booked")
        due_back.append(
            {
                "patient": queue.patient_ref(written.patient, written.allergy_count, date),
                "doctor": queue.doctor_ref(written.doctor),
                "asked_on": written.consultation.started_at.astimezone(zone).date(),
                "consultation_id": written.consultation.id,
                "state": state,
                "booked_for": booked_for.get(patient_id) if state == "booked" else None,
            }
        )
    # Whoever still needs a call first.
    due_back.sort(key=lambda item: (order[item["state"]], item["patient"]["full_name"]))
    shape["due_back"] = due_back

    if reach.narrowed and reach.doctor_id is not None:
        # The notes for whoever is in the room now are being written, not
        # left behind, so they are not counted among the unfinished.
        writing = {
            lane["now_seeing"]["consultation_id"]
            for lane in lanes
            if lane["now_seeing"] and lane["now_seeing"]["consultation_id"]
        }
        drafts, total = await consultations.listed(
            doctor_id=reach.doctor_id,
            patient_id=None,
            status=notes.DRAFT,
            limit=SHOWN + len(writing),
            offset=0,
        )
        drafts = [written for written in drafts if written.consultation.id not in writing]
        shape["unfinished"] = [
            {
                "consultation_id": written.consultation.id,
                "patient": queue.patient_ref(written.patient, written.allergy_count, date),
                "visit_date": written.consultation.started_at.astimezone(zone).date(),
                "chief_complaint": written.consultation.chief_complaint,
            }
            for written in drafts[:SHOWN]
        ]
        shape["unfinished_total"] = total - len(writing)

        reports, shape["results_total"] = await LabRepository(
            session, organization_id
        ).to_review(reach.doctor_id, limit=SHOWN)
        shape["results"] = [
            {
                "order_id": report.order.id,
                "patient": queue.patient_ref(report.patient, report.allergy_count, date),
                "test_name": report.order.test_name,
                "reported_on": report.order.reported_on,
                "urgent": report.order.urgent,
                "flagged": lab.flagged(report.values),
            }
            for report in reports
        ]

    return shape
