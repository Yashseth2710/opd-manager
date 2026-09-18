"""The day's queue: who has arrived, who is next, who is in the room.

A patient joins by checking in against today's appointment, or as a walk-in
with none. From there the doctor's side calls them, sees them and finishes,
and every step is written back to the appointment so the day's book and the
queue never disagree about where somebody is.

Order in the line is arrival order, with anyone marked urgent ahead of
everyone else. A patient who missed their call and is recalled goes back to
their own number, which puts them near the front again.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound, ValidationFailed
from app.models import Appointment, Doctor, Organization, Patient, QueueEntry
from app.models import appointment as booked
from app.models import queue as line
from app.models.doctor import DAY_NAMES
from app.repositories.appointments import AppointmentRepository, EventRepository
from app.repositories.doctors import DoctorRepository
from app.repositories.patients import PatientRepository
from app.repositories.queue import Placed, QueueRepository
from app.schemas.queue import WalkIn
from app.services.appointments import (
    Reach,
    fetch,
    record_event,
    spoken_day,
    spoken_time,
)
from app.services.doctors import (
    INACTIVE_DOCTOR,
    NO_CLINIC,
    DoctorInactive,
    clinic_now,
    clinic_today,
    clinic_zone,
    day_bounds,
    describe_leave,
    effective_slot_minutes,
    plan_day,
)
from app.services.patients import PatientArchived, age_label

# How many of a doctor's latest consultations the expected wait is drawn from.
# Enough to smooth out one long one, few enough to follow the day as it goes.
RECENT = 10

# Until this many have been seen today, the doctor's appointment length is a
# better guess than an average of one or two, which a single quick
# prescription renewal would drag down to a minute.
TRUSTED_AFTER = 3


class QueueEntryNotFound(NotFound):
    code = "QUEUE_NOT_FOUND"
    message = "That patient is not in the queue."


class AlreadyCheckedIn(AppError):
    code = "QUEUE_ALREADY_CHECKED_IN"
    status = 409
    message = "This patient is already in the queue."


class HasAppointment(AppError):
    code = "QUEUE_HAS_APPOINTMENT"
    status = 409
    message = "This patient has an appointment today. Check that in instead."


class InvalidTransition(AppError):
    code = "QUEUE_INVALID_TRANSITION"
    status = 409
    message = "That cannot be done to this place in the queue now."


class NotToday(ValidationFailed):
    code = "QUEUE_NOT_TODAY"


def _first_name(patient: Patient) -> str:
    return patient.preferred_name or patient.first_name


# --- Joining the queue -----------------------------------------------------


async def _open_for_today(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    doctor: Doctor,
    today: dt.date,
) -> None:
    """Refuses a place with a doctor nobody can be seen by today."""
    plan = await plan_day(
        session, organization_id=organization_id, clinic=clinic, doctor=doctor, day=today
    )
    name = doctor.display_name
    if plan.closed == INACTIVE_DOCTOR:
        raise DoctorInactive(f"{name} is not seeing patients at the moment.")
    if plan.closed == NO_CLINIC:
        raise InvalidTransition(f"{name} has no {DAY_NAMES[today.weekday()]} clinic.")
    if plan.closed is not None:
        raise InvalidTransition(f"{name} is on leave today.")


async def _refuse_second_place(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    patient: Patient,
    today: dt.date,
) -> None:
    held = await QueueRepository(session, organization_id).live_place(patient.id, today)
    if held is None:
        return
    raise AlreadyCheckedIn(
        f"{_first_name(patient)} is already in the queue for "
        f"{held.doctor.display_name}, token {held.entry.token_number}."
    )


@asynccontextmanager
async def _refusing_clashes() -> AsyncIterator[None]:
    """The database's refusals, in the desk's words.

    Each check has already been made before the write, so landing here means
    another desk did the same thing in the moment between.
    """
    try:
        yield
    except IntegrityError as exc:
        text = str(exc.orig)
        if "uq_queue_patient_live" in text or "uq_queue_appointment" in text:
            raise AlreadyCheckedIn from exc
        if "uq_queue_doctor_called" in text:
            raise InvalidTransition(
                "Somebody else has just been called for this doctor."
            ) from exc
        if "uq_queue_doctor_in_room" in text:
            raise InvalidTransition("This doctor already has a patient with them.") from exc
        if "uq_queue_token" in text:
            raise InvalidTransition("Two check-ins crossed. Try again.") from exc
        raise


async def _place(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    actor_id: uuid.UUID,
    patient: Patient,
    doctor: Doctor,
    appointment: Appointment | None,
    priority: str,
    reason: str | None = None,
) -> QueueEntry:
    today = clinic_today(clinic)
    queue = QueueRepository(session, organization_id)
    # Held until the request ends, so the next desk to check somebody in for
    # this doctor reads the number this one takes.
    await queue.lock_doctor(doctor.id)
    entry = QueueEntry(
        appointment_id=appointment.id if appointment else None,
        patient_id=patient.id,
        doctor_id=doctor.id,
        token_date=today,
        token_number=await queue.next_token(doctor.id, today),
        priority=priority,
        status=line.WAITING,
        reason=reason or None,
        checked_in_at=dt.datetime.now(dt.UTC),
        checked_in_by_id=actor_id,
    )
    async with _refusing_clashes():
        await queue.add(entry)
    return entry


async def check_in(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    appointment_id: uuid.UUID,
    priority: str,
) -> QueueEntry:
    listed = await fetch(
        session,
        organization_id=organization_id,
        reach=reach,
        appointment_id=appointment_id,
        lock=True,
    )
    appointment, patient, doctor = listed.appointment, listed.patient, listed.doctor
    zone = clinic_zone(clinic)
    today = clinic_today(clinic)
    day = appointment.scheduled_start.astimezone(zone).date()

    if appointment.status not in booked.OPEN:
        if appointment.status in (booked.CANCELLED, booked.NO_SHOW):
            raise InvalidTransition(
                "This appointment was cancelled."
                if appointment.status == booked.CANCELLED
                else "This appointment was marked as a no-show."
            )
        if appointment.status == booked.COMPLETED:
            raise InvalidTransition("The patient has already been seen.")
        token = await QueueRepository(session, organization_id).for_appointments(
            {appointment.id}
        )
        raise AlreadyCheckedIn(
            f"Already checked in, token {token[appointment.id]}."
            if appointment.id in token
            else "Already checked in."
        )
    if day != today:
        said = spoken_day(day, beside=today)
        raise NotToday(
            {"date": f"This appointment is on {said}, not today."},
            f"This appointment is on {said}, not today. "
            "Move it to today first if they have come in early.",
        )
    if patient.is_archived:
        raise PatientArchived("This record is archived. Restore it before checking them in.")

    await _open_for_today(
        session, organization_id=organization_id, clinic=clinic, doctor=doctor, today=today
    )
    await _refuse_second_place(
        session, organization_id=organization_id, patient=patient, today=today
    )

    entry = await _place(
        session,
        organization_id=organization_id,
        clinic=clinic,
        actor_id=actor_id,
        patient=patient,
        doctor=doctor,
        appointment=appointment,
        priority=priority,
    )
    before = appointment.status
    appointment.status = booked.WAITING
    await session.flush()
    await record_event(
        session,
        organization_id=organization_id,
        appointment=appointment,
        event=booked.CHECKED_IN_EVENT,
        from_status=before,
        actor_id=actor_id,
        detail=f"Token {entry.token_number}",
    )
    return entry


async def walk_in(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    body: WalkIn,
) -> QueueEntry:
    patient = await PatientRepository(session, organization_id).get(body.patient_id)
    if patient is None:
        raise ValidationFailed({"patient_id": "That patient is not registered here."})
    if patient.is_archived:
        raise PatientArchived("This record is archived. Restore it before checking them in.")

    doctor = await DoctorRepository(session, organization_id).get(body.doctor_id)
    if doctor is None or not reach.covers(doctor.id):
        raise ValidationFailed({"doctor_id": "That doctor does not work here."})

    today = clinic_today(clinic)
    await _open_for_today(
        session, organization_id=organization_id, clinic=clinic, doctor=doctor, today=today
    )
    await _refuse_second_place(
        session, organization_id=organization_id, patient=patient, today=today
    )

    # Somebody booked for later today who turns up early is checked in
    # against that booking, or the slot sits there held for nobody.
    opens_at, closes_at = day_bounds(clinic, today)
    for row in await AppointmentRepository(session, organization_id).between(
        opens_at, closes_at, doctor_id=doctor.id
    ):
        if row.patient.id == patient.id and row.appointment.status in booked.OPEN:
            starts = row.appointment.scheduled_start.astimezone(clinic_zone(clinic))
            raise HasAppointment(
                f"{_first_name(patient)} has an appointment with {doctor.display_name} "
                f"at {spoken_time(starts.time())} today. Check that in instead."
            )

    return await _place(
        session,
        organization_id=organization_id,
        clinic=clinic,
        actor_id=actor_id,
        patient=patient,
        doctor=doctor,
        appointment=None,
        priority=body.priority,
        reason=body.reason,
    )


# --- Moving through it -----------------------------------------------------


async def _fetch(
    session: AsyncSession, organization_id: uuid.UUID, reach: Reach, entry_id: uuid.UUID
) -> Placed:
    """One place, locked along with its appointment for the rest of the
    request, so a double click is two turns rather than two writes."""
    queue = QueueRepository(session, organization_id)
    found = await queue.one(entry_id, lock=True)
    # Outside a doctor's own line reads as absent, the same as another clinic.
    if found is None or not reach.covers(found.doctor.id):
        raise QueueEntryNotFound
    if found.entry.appointment_id is not None:
        await queue.lock_appointment(found.entry.appointment_id)
    return found


_WHERE_THEY_ARE = {
    line.WAITING: "They are still waiting.",
    line.CALLED: "They have been called and not come in yet.",
    line.IN_CONSULTATION: "They are with the doctor now.",
    line.COMPLETED: "They have already been seen.",
    line.SKIPPED: "They missed their call. Recall them first.",
    line.NO_SHOW: "They have been marked as gone.",
}


def _require(entry: QueueEntry, *allowed: str) -> None:
    if entry.status not in allowed:
        raise InvalidTransition(_WHERE_THEY_ARE[entry.status])


def _require_today(entry: QueueEntry, clinic: Organization) -> None:
    today = clinic_today(clinic)
    if entry.token_date != today:
        raise InvalidTransition(
            f"This place was in the queue on {spoken_day(entry.token_date, beside=today)}."
        )


async def _follow(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    placed: Placed,
    status: str,
    event: str,
    actor_id: uuid.UUID,
    detail: str | None = None,
) -> None:
    """Writes the queue's step onto the appointment it came from, if any."""
    appointment = placed.appointment
    if appointment is None or appointment.status == status:
        return
    before = appointment.status
    appointment.status = status
    await session.flush()
    await record_event(
        session,
        organization_id=organization_id,
        appointment=appointment,
        event=event,
        from_status=before,
        actor_id=actor_id,
        detail=detail,
    )


async def call(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    entry_id: uuid.UUID,
) -> QueueEntry:
    placed = await _fetch(session, organization_id, reach, entry_id)
    entry = placed.entry
    _require(entry, line.WAITING)
    _require_today(entry, clinic)

    queue = QueueRepository(session, organization_id)
    await queue.lock_doctor(entry.doctor_id)
    waiting_on = await queue.first_with(entry.doctor_id, entry.token_date, line.CALLED)
    if waiting_on is not None:
        raise InvalidTransition(
            f"Token {waiting_on.token_number} has been called and has not come in yet. "
            "Start their consultation or mark them not here first."
        )

    entry.status = line.CALLED
    entry.called_at = dt.datetime.now(dt.UTC)
    async with _refusing_clashes():
        await session.flush()
    return entry


async def start(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> QueueEntry:
    """Brings a patient into the room: the one who was called, or one still
    waiting whom the doctor has simply waved in."""
    placed = await _fetch(session, organization_id, reach, entry_id)
    entry = placed.entry
    _require(entry, line.CALLED, line.WAITING)
    _require_today(entry, clinic)

    queue = QueueRepository(session, organization_id)
    await queue.lock_doctor(entry.doctor_id)
    in_room = await queue.first_with(entry.doctor_id, entry.token_date, line.IN_CONSULTATION)
    if in_room is not None:
        raise InvalidTransition(
            f"Token {in_room.token_number} is still with {placed.doctor.display_name}. "
            "Finish that consultation first."
        )

    now = dt.datetime.now(dt.UTC)
    entry.status = line.IN_CONSULTATION
    entry.called_at = entry.called_at or now
    entry.started_at = now
    async with _refusing_clashes():
        await session.flush()
    await _follow(
        session,
        organization_id=organization_id,
        placed=placed,
        status=booked.IN_CONSULTATION,
        event=booked.STARTED,
        actor_id=actor_id,
    )
    return entry


async def complete(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> QueueEntry:
    placed = await _fetch(session, organization_id, reach, entry_id)
    entry = placed.entry
    _require(entry, line.IN_CONSULTATION)

    entry.status = line.COMPLETED
    entry.completed_at = dt.datetime.now(dt.UTC)
    await session.flush()
    await _follow(
        session,
        organization_id=organization_id,
        placed=placed,
        status=booked.COMPLETED,
        event=booked.SEEN,
        actor_id=actor_id,
    )
    return entry


async def skip(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    entry_id: uuid.UUID,
) -> QueueEntry:
    """Called and not here. They keep their number for when they come back."""
    placed = await _fetch(session, organization_id, reach, entry_id)
    entry = placed.entry
    _require(entry, line.CALLED)
    entry.status = line.SKIPPED
    await session.flush()
    return entry


async def recall(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    entry_id: uuid.UUID,
) -> QueueEntry:
    placed = await _fetch(session, organization_id, reach, entry_id)
    entry = placed.entry
    _require(entry, line.SKIPPED)
    _require_today(entry, clinic)
    entry.status = line.WAITING
    await session.flush()
    return entry


async def mark_gone(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> QueueEntry:
    """Left without being seen. The appointment becomes a no-show, which is
    what it cost the clinic."""
    placed = await _fetch(session, organization_id, reach, entry_id)
    entry = placed.entry
    _require(entry, line.WAITING, line.CALLED, line.SKIPPED)

    entry.status = line.NO_SHOW
    entry.completed_at = dt.datetime.now(dt.UTC)
    await session.flush()
    await _follow(
        session,
        organization_id=organization_id,
        placed=placed,
        status=booked.NO_SHOW,
        event=booked.LEFT,
        actor_id=actor_id,
        detail=f"Left the queue, token {entry.token_number}",
    )
    return entry


async def set_priority(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    entry_id: uuid.UUID,
    priority: str,
) -> QueueEntry:
    placed = await _fetch(session, organization_id, reach, entry_id)
    entry = placed.entry
    _require(entry, line.WAITING, line.SKIPPED)
    entry.priority = priority
    await session.flush()
    return entry


async def undo(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> uuid.UUID | None:
    """Takes back a check-in made by mistake, before anybody has called them.

    The place goes altogether, since it never meant anything, and the
    appointment goes back to how it stood before. Returns that appointment,
    for the answer to show.
    """
    placed = await _fetch(session, organization_id, reach, entry_id)
    entry = placed.entry
    if entry.status != line.WAITING or entry.called_at is not None:
        raise InvalidTransition(
            "They have already been called, so the check-in can no longer be undone."
        )

    appointment = placed.appointment
    await session.delete(entry)
    await session.flush()
    if appointment is None:
        return None

    history = await EventRepository(session, organization_id).for_appointment(appointment.id)
    arrival = next(
        (event for event in reversed(history) if event.event == booked.CHECKED_IN_EVENT), None
    )
    was = arrival.from_status if arrival and arrival.from_status in booked.OPEN else None
    before = appointment.status
    appointment.status = was or booked.SCHEDULED
    await session.flush()
    await record_event(
        session,
        organization_id=organization_id,
        appointment=appointment,
        event=booked.CHECK_IN_UNDONE,
        from_status=before,
        actor_id=actor_id,
    )
    return appointment.id


# --- Reading it ------------------------------------------------------------


def _minutes(span: dt.timedelta) -> int:
    return max(0, int(span.total_seconds() // 60))


def _average(durations: list[dt.timedelta], fallback: int) -> int:
    if len(durations) < TRUSTED_AFTER:
        return fallback
    mean = sum(durations, dt.timedelta()) / len(durations)
    return max(1, round(mean.total_seconds() / 60))


def _patient_ref(placed_patient: Patient, allergy_count: int, today: dt.date) -> dict[str, Any]:
    return {
        "id": placed_patient.id,
        "patient_number": placed_patient.patient_number,
        "full_name": placed_patient.full_name,
        "preferred_name": placed_patient.preferred_name,
        "phone": placed_patient.phone,
        "age": age_label(placed_patient.date_of_birth, today),
        "gender": placed_patient.gender,
        "status": placed_patient.status,
        "allergy_count": allergy_count,
    }


def _doctor_ref(doctor: Doctor) -> dict[str, Any]:
    return {
        "id": doctor.id,
        "display_name": doctor.display_name,
        "speciality": doctor.speciality,
        "room": doctor.room,
        "status": doctor.status,
    }


def _present(
    placed: Placed,
    *,
    clinic: Organization,
    now: dt.datetime,
    position: int | None = None,
    expected: int | None = None,
) -> dict[str, Any]:
    entry, appointment = placed.entry, placed.appointment
    zone = clinic_zone(clinic)

    if entry.started_at is not None:
        waited = entry.started_at - entry.checked_in_at
    elif entry.completed_at is not None:
        waited = entry.completed_at - entry.checked_in_at
    else:
        waited = now - entry.checked_in_at

    return {
        "id": entry.id,
        "token": entry.token_number,
        "status": entry.status,
        "priority": entry.priority,
        "patient": _patient_ref(placed.patient, placed.allergy_count, now.date()),
        "doctor": _doctor_ref(placed.doctor),
        "appointment": {
            "id": appointment.id,
            "start_time": appointment.scheduled_start.astimezone(zone).time(),
            "end_time": appointment.scheduled_end.astimezone(zone).time(),
            "appointment_type": appointment.appointment_type,
            "reason": appointment.reason,
            "status": appointment.status,
        }
        if appointment is not None
        else None,
        "reason": entry.reason,
        "checked_in_at": entry.checked_in_at,
        "called_at": entry.called_at,
        "started_at": entry.started_at,
        "completed_at": entry.completed_at,
        "waited_minutes": _minutes(waited),
        "position": position,
        "expected_wait_minutes": expected,
    }


def _line_order(placed: Placed) -> tuple[int, int]:
    return (0 if placed.entry.priority == line.URGENT else 1, placed.entry.token_number)


def _lane(
    doctor: Doctor,
    *,
    clinic: Organization,
    now: dt.datetime,
    closed: str | None,
    places: list[Placed],
    arrivals: list[Any],
) -> dict[str, Any]:
    zone = clinic_zone(clinic)
    in_room = next((p for p in places if p.entry.status == line.IN_CONSULTATION), None)
    called = next((p for p in places if p.entry.status == line.CALLED), None)
    waiting = sorted((p for p in places if p.entry.status == line.WAITING), key=_line_order)
    skipped = sorted((p for p in places if p.entry.status == line.SKIPPED), key=_line_order)
    done = sorted(
        (p for p in places if p.entry.status in line.DONE),
        key=lambda p: p.entry.completed_at or p.entry.checked_in_at,
        reverse=True,
    )

    seen = [
        p.entry.completed_at - p.entry.started_at
        for p in sorted(done, key=lambda p: p.entry.completed_at or now, reverse=True)
        if p.entry.status == line.COMPLETED and p.entry.started_at and p.entry.completed_at
    ][:RECENT]
    average = _average(seen, effective_slot_minutes(doctor, clinic))

    # Whoever is in the room has the rest of an average consultation left,
    # and whoever has been called is next through the door.
    ahead = 0
    if in_room is not None and in_room.entry.started_at is not None:
        ahead += max(0, average - _minutes(now - in_room.entry.started_at))
    if called is not None:
        ahead += average

    return {
        "doctor": _doctor_ref(doctor),
        "closed": closed,
        "now_seeing": _present(in_room, clinic=clinic, now=now) if in_room else None,
        "called": _present(called, clinic=clinic, now=now) if called else None,
        "waiting": [
            _present(
                placed,
                clinic=clinic,
                now=now,
                position=index + 1,
                expected=ahead + index * average,
            )
            for index, placed in enumerate(waiting)
        ],
        "skipped": [_present(placed, clinic=clinic, now=now) for placed in skipped],
        "done": [_present(placed, clinic=clinic, now=now) for placed in done],
        "expected": [
            {
                "id": row.appointment.id,
                "patient": _patient_ref(row.patient, row.allergy_count, now.date()),
                "start_time": row.appointment.scheduled_start.astimezone(zone).time(),
                "end_time": row.appointment.scheduled_end.astimezone(zone).time(),
                "appointment_type": row.appointment.appointment_type,
                "status": row.appointment.status,
                "reason": row.appointment.reason,
                "is_late": row.appointment.scheduled_start <= now,
            }
            for row in arrivals
        ],
        "seen_count": sum(1 for p in done if p.entry.status == line.COMPLETED),
        "average_minutes": average,
    }


async def day(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    doctor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Today's queue, one lane per doctor with anything to show.

    A doctor on leave still gets a lane, so the desk can see why nobody is
    joining it. One with no clinic today and nobody booked is left out.
    """
    today = clinic_today(clinic)
    shape: dict[str, Any] = {
        "date": today,
        "day_name": DAY_NAMES[today.weekday()],
        "lanes": [],
        "only_doctor_id": reach.doctor_id if reach.narrowed else None,
        "unlinked": reach.unlinked,
    }
    if reach.unlinked:
        return shape

    only = reach.doctor_id if reach.narrowed else doctor_id
    now = clinic_now(clinic)
    places = await QueueRepository(session, organization_id).on_day(today, doctor_id=only)
    opens_at, closes_at = day_bounds(clinic, today)
    booked_today = await AppointmentRepository(session, organization_id).between(
        opens_at, closes_at, doctor_id=only
    )
    arrivals = [row for row in booked_today if row.appointment.status in booked.OPEN]

    # Polled every few seconds by every screen showing the queue, so the
    # doctors' days come from one query rather than a day plan each.
    # Joining a line still goes through the full plan.
    duty = {
        row.doctor.id: row
        for row in await DoctorRepository(session, organization_id).on_duty(today)
        if only is None or row.doctor.id == only
    }
    doctors: dict[uuid.UUID, Doctor] = {key: row.doctor for key, row in duty.items()}
    for placed in places:
        doctors.setdefault(placed.doctor.id, placed.doctor)
    for row in arrivals:
        doctors.setdefault(row.doctor.id, row.doctor)

    lanes: list[dict[str, Any]] = []
    for doctor in doctors.values():
        mine = [p for p in places if p.doctor.id == doctor.id]
        expected = [row for row in arrivals if row.doctor.id == doctor.id]
        on = duty.get(doctor.id)
        closed: str | None = None
        if not doctor.is_active or on is None:
            closed = "Not seeing patients at the moment."
        elif not on.sits:
            closed = f"No {DAY_NAMES[today.weekday()]} clinic."
        elif on.leave is not None:
            closed = describe_leave(on.leave, today, today)
        # Somebody on leave keeps a lane, so the desk can see why it is shut.
        on_leave = on is not None and on.sits and on.leave is not None
        if closed and not on_leave and not mine and not expected:
            continue
        lanes.append(
            _lane(
                doctor,
                clinic=clinic,
                now=now,
                closed=closed,
                places=mine,
                arrivals=expected,
            )
        )

    # The busiest lanes first, then by name, so the desk's eye lands where
    # the people are.
    lanes.sort(
        key=lambda lane: (
            -(len(lane["waiting"]) + (1 if lane["now_seeing"] else 0) + len(lane["expected"])),
            lane["doctor"]["display_name"],
        )
    )
    shape["lanes"] = lanes
    return shape


async def one(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    entry_id: uuid.UUID,
) -> dict[str, Any]:
    """One place, with its position worked out against the rest of its line."""
    placed = await QueueRepository(session, organization_id).one(entry_id)
    if placed is None or not reach.covers(placed.doctor.id):
        raise QueueEntryNotFound
    whole = await day(
        session,
        organization_id=organization_id,
        clinic=clinic,
        reach=reach,
        doctor_id=placed.doctor.id,
    )
    for lane in whole["lanes"]:
        for group in ("waiting", "skipped", "done"):
            for shown in lane[group]:
                if shown["id"] == entry_id:
                    return dict(shown)
        for single in ("now_seeing", "called"):
            if lane[single] and lane[single]["id"] == entry_id:
                return dict(lane[single])
    # A place from another day, which the day's lanes do not carry.
    return _present(placed, clinic=clinic, now=clinic_now(clinic))
