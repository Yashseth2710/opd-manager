"""Booking appointments and everything that happens to one afterwards.

A booking is only ever made into a slot the doctor's day plan offers, which
is the same plan the free-times panel shows, so the desk cannot be shown one
set of times and have the server accept another. The database then holds
the line against the one thing no check in here can see: somebody else
booking the same slot a moment earlier.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound, ValidationFailed
from app.core.permissions import DOCTOR
from app.models import Appointment, AppointmentEvent, Doctor, Organization, Patient
from app.models.appointment import (
    BOOKED,
    CANCELLED,
    CANCELLED_EVENT,
    COMPLETED,
    CONFIRMED,
    CONFIRMED_EVENT,
    EDITED,
    FOLLOW_UP,
    IN_CONSULTATION,
    MARKED_NO_SHOW,
    NO_SHOW,
    OPEN,
    RESCHEDULED,
    SCHEDULED,
    WAITING,
)
from app.models.doctor import DAY_NAMES
from app.repositories.appointments import AppointmentRepository, EventRepository, Listed
from app.repositories.consultations import ConsultationRepository
from app.repositories.doctors import DoctorRepository, names_of
from app.repositories.patients import PatientRepository
from app.repositories.queue import QueueRepository
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate
from app.services.doctors import (
    BOOKED as SLOT_BOOKED,
)
from app.services.doctors import (
    GONE,
    INACTIVE_DOCTOR,
    NO_CLINIC,
    ON_LEAVE,
    DoctorInactive,
    at_clinic,
    clinic_now,
    clinic_today,
    clinic_zone,
    day_bounds,
    effective_fee,
    plan_day,
)
from app.services.patients import PatientArchived, PatientNotFound, age_label

# Far enough for a six-monthly review, near enough that a typo in the year is
# caught rather than booked.
BOOKING_HORIZON_DAYS = 366

# What a patient's page shows of the past. Older visits belong to the
# timeline, which reads the whole history.
HISTORY_SHOWN = 30


class AppointmentNotFound(NotFound):
    code = "APPT_NOT_FOUND"
    message = "That appointment could not be found."


class SlotUnavailable(AppError):
    code = "APPT_SLOT_UNAVAILABLE"
    status = 409
    message = "That time has just been booked. Pick another one."


class PatientBusy(AppError):
    code = "APPT_PATIENT_BUSY"
    status = 409
    message = "This patient already has an appointment at that time."


class InvalidTransition(AppError):
    code = "APPT_INVALID_TRANSITION"
    status = 409
    message = "That cannot be done to this appointment now."


class OutsideHours(ValidationFailed):
    code = "APPT_OUTSIDE_WORKING_HOURS"


class DoctorOnLeave(ValidationFailed):
    code = "APPT_DOCTOR_ON_LEAVE"


class PastTime(ValidationFailed):
    code = "APPT_PAST_DATE"


def _refuse(error: type[ValidationFailed], field: str, sentence: str) -> ValidationFailed:
    # The sentence goes in both places: beside the field, and as the message
    # for anything that shows one line rather than a form.
    return error({field: sentence}, sentence)


@dataclass(frozen=True)
class Reach:
    """Whose appointments a caller may see and touch.

    A doctor's role sees only their own list, which means the one profile
    linked to their account. A doctor's account with no profile linked yet
    sees nothing at all rather than everybody's.
    """

    narrowed: bool
    doctor_id: uuid.UUID | None = None

    @property
    def unlinked(self) -> bool:
        return self.narrowed and self.doctor_id is None

    def covers(self, doctor_id: uuid.UUID) -> bool:
        return not self.narrowed or self.doctor_id == doctor_id


async def reach_of(
    session: AsyncSession, *, organization_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> Reach:
    if role != DOCTOR:
        return Reach(narrowed=False)
    profile = await DoctorRepository(session, organization_id).for_account(user_id)
    return Reach(narrowed=True, doctor_id=profile.id if profile else None)


def spoken_time(value: dt.time) -> str:
    """ "9:00 am", the way a clinic writes its hours up."""
    twelve = value.hour % 12 or 12
    return f"{twelve}:{value.minute:02d} {'am' if value.hour < 12 else 'pm'}"


def spoken_day(value: dt.date, *, beside: dt.date | None = None) -> str:
    """ "Mon 22 Sep", with the year only where it would otherwise mislead."""
    written = f"{value:%a} {value.day} {value:%b}"
    if beside is not None and beside.year != value.year:
        written = f"{written} {value.year}"
    return written


def _first_name(patient: Patient) -> str:
    return patient.preferred_name or patient.first_name


async def registered_patient(
    session: AsyncSession, organization_id: uuid.UUID, patient_id: uuid.UUID
) -> Patient:
    patient = await PatientRepository(session, organization_id).get(patient_id)
    # Another clinic's patient reads as a field that matches nobody here,
    # never as confirmation that the record exists somewhere.
    if patient is None:
        raise ValidationFailed({"patient_id": "That patient is not registered here."})
    if patient.is_archived:
        raise PatientArchived("This record is archived. Restore it before booking.")
    return patient


async def bookable_doctor(
    session: AsyncSession, organization_id: uuid.UUID, doctor_id: uuid.UUID, reach: Reach
) -> Doctor:
    doctor = await DoctorRepository(session, organization_id).get(doctor_id)
    if doctor is None:
        raise ValidationFailed({"doctor_id": "That doctor does not work here."})
    if not reach.covers(doctor.id):
        raise ValidationFailed({"doctor_id": "You can only book into your own list."})
    if not doctor.is_active:
        raise DoctorInactive(
            f"{doctor.display_name} is not seeing patients at the moment, so cannot be booked."
        )
    return doctor


async def _place(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    doctor: Doctor,
    day: dt.date,
    start: dt.time,
    ignoring: uuid.UUID | None = None,
) -> tuple[dt.datetime, dt.datetime]:
    """Finds the slot being asked for, or says in plain words why not."""
    today = clinic_today(clinic)
    if day < today:
        raise _refuse(PastTime, "date", "That day has already gone.")
    if day > today + dt.timedelta(days=BOOKING_HORIZON_DAYS):
        raise _refuse(OutsideHours, "date", "Appointments can be booked up to a year ahead.")

    plan = await plan_day(
        session,
        organization_id=organization_id,
        clinic=clinic,
        doctor=doctor,
        day=day,
        ignoring=ignoring,
    )
    name = doctor.display_name

    if plan.closed == INACTIVE_DOCTOR:
        raise DoctorInactive(
            f"{name} is not seeing patients at the moment, so cannot be booked."
        )
    if plan.closed == NO_CLINIC:
        raise _refuse(OutsideHours, "date", f"{name} has no {DAY_NAMES[day.weekday()]} clinic.")
    if plan.closed == ON_LEAVE:
        raise _refuse(DoctorOnLeave, "date", f"{name} is on leave that day.")

    slot = plan.slot_at(start)
    if slot is None:
        if any(begins <= start < ends for begins, ends in plan.away):
            raise _refuse(
                DoctorOnLeave, "start_time", f"{name} is away at {spoken_time(start)}."
            )
        if any(
            block.break_start
            and block.break_end
            and block.break_start <= start < block.break_end
            for block in plan.blocks
        ):
            raise _refuse(OutsideHours, "start_time", f"That is during {name}'s break.")
        raise _refuse(
            OutsideHours,
            "start_time",
            f"{spoken_time(start)} is not one of {name}'s appointment times "
            f"on {DAY_NAMES[day.weekday()]}.",
        )

    if slot.state == GONE:
        raise _refuse(PastTime, "start_time", "That time has already gone.")
    if slot.state == SLOT_BOOKED:
        raise SlotUnavailable

    return at_clinic(clinic, day, slot.start_time), at_clinic(clinic, day, slot.end_time)


async def _check_patient_free(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    patient: Patient,
    starts: dt.datetime,
    ends: dt.datetime,
    ignoring: uuid.UUID | None = None,
) -> None:
    clash = await AppointmentRepository(session, organization_id).patient_clash(
        patient.id, starts, ends, ignoring=ignoring
    )
    if clash is None:
        return
    when = clash.appointment.scheduled_start.astimezone(clinic_zone(clinic))
    raise PatientBusy(
        f"{_first_name(patient)} already has an appointment with "
        f"{clash.doctor.display_name} at {spoken_time(when.time())} that day."
    )


@asynccontextmanager
async def _refusing_clashes() -> AsyncIterator[None]:
    """Turns the database's refusal into the desk's language.

    The checks before a write have already looked, so a refusal here means
    somebody else booked the same time in the moment between the look and
    the write.
    """
    try:
        yield
    except IntegrityError as exc:
        text = str(exc.orig)
        if "ex_appointments_doctor_overlap" in text:
            raise SlotUnavailable from exc
        if "ex_appointments_patient_overlap" in text:
            raise PatientBusy from exc
        raise


async def _actor_name(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    return (await names_of(session, {user_id})).get(user_id)


async def record_event(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    appointment: Appointment,
    event: str,
    from_status: str | None,
    actor_id: uuid.UUID,
    detail: str | None = None,
) -> None:
    await EventRepository(session, organization_id).add(
        AppointmentEvent(
            appointment_id=appointment.id,
            event=event,
            from_status=from_status,
            to_status=appointment.status,
            detail=detail,
            actor_id=actor_id,
            actor_name=await _actor_name(session, actor_id),
        )
    )


async def book(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    body: AppointmentCreate,
) -> Appointment:
    patient = await registered_patient(session, organization_id, body.patient_id)
    doctor = await bookable_doctor(session, organization_id, body.doctor_id, reach)
    # Before the slot is looked at, so a second desk booking it at the same
    # moment waits here and then sees this booking.
    await AppointmentRepository(session, organization_id).take_turns(doctor.id, patient.id)
    starts, ends = await _place(
        session,
        organization_id=organization_id,
        clinic=clinic,
        doctor=doctor,
        day=body.date,
        start=body.start_time,
    )
    await _check_patient_free(
        session,
        organization_id=organization_id,
        clinic=clinic,
        patient=patient,
        starts=starts,
        ends=ends,
    )

    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        scheduled_start=starts,
        scheduled_end=ends,
        appointment_type=body.appointment_type,
        source=body.source,
        status=SCHEDULED,
        reason=body.reason or None,
        notes=body.notes or None,
        booked_by_id=actor_id,
    )
    # Stamped with the clinic by the repository, never taken from the body.
    async with _refusing_clashes():
        await AppointmentRepository(session, organization_id).add(appointment)

    await record_event(
        session,
        organization_id=organization_id,
        appointment=appointment,
        event=BOOKED,
        from_status=None,
        actor_id=actor_id,
    )
    return appointment


async def fetch(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    appointment_id: uuid.UUID,
    lock: bool = False,
) -> Listed:
    found = await AppointmentRepository(session, organization_id).one(appointment_id, lock=lock)
    # Outside a doctor's own list reads as absent, the same as another clinic.
    if found is None or not reach.covers(found.doctor.id):
        raise AppointmentNotFound
    return found


_CLOSED_BECAUSE = {
    CANCELLED: "This appointment was cancelled.",
    NO_SHOW: "This appointment was marked as a no-show.",
    WAITING: "The patient has checked in and is in the queue.",
    IN_CONSULTATION: "The patient is with the doctor now.",
    COMPLETED: "The patient has already been seen.",
}


def _require_open(appointment: Appointment) -> None:
    if appointment.status in OPEN:
        return
    raise InvalidTransition(
        _CLOSED_BECAUSE.get(appointment.status, "This appointment can no longer be changed.")
    )


async def update(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    appointment_id: uuid.UUID,
    body: AppointmentUpdate,
) -> Appointment:
    listed = await fetch(
        session,
        organization_id=organization_id,
        reach=reach,
        appointment_id=appointment_id,
        lock=True,
    )
    appointment = listed.appointment
    _require_open(appointment)

    supplied = body.model_dump(exclude_unset=True)
    zone = clinic_zone(clinic)
    was_start = appointment.scheduled_start.astimezone(zone)
    was_doctor = listed.doctor

    wants_move = any(
        supplied.get(key) is not None for key in ("doctor_id", "date", "start_time")
    )
    if wants_move:
        doctor = (
            await bookable_doctor(session, organization_id, supplied["doctor_id"], reach)
            if supplied.get("doctor_id") and supplied["doctor_id"] != was_doctor.id
            else was_doctor
        )
        day = supplied.get("date") or was_start.date()
        start = supplied.get("start_time") or was_start.time()
        moved = doctor.id != was_doctor.id or at_clinic(clinic, day, start) != was_start

        if moved:
            await AppointmentRepository(session, organization_id).take_turns(
                doctor.id, listed.patient.id
            )
            starts, ends = await _place(
                session,
                organization_id=organization_id,
                clinic=clinic,
                doctor=doctor,
                day=day,
                start=start,
                ignoring=appointment.id,
            )
            await _check_patient_free(
                session,
                organization_id=organization_id,
                clinic=clinic,
                patient=listed.patient,
                starts=starts,
                ends=ends,
                ignoring=appointment.id,
            )

            detail = f"Moved from {spoken_day(was_start.date(), beside=day)}, "
            detail += spoken_time(was_start.time())
            if doctor.id != was_doctor.id:
                detail += f" with {was_doctor.display_name}"

            before = appointment.status
            appointment.doctor_id = doctor.id
            appointment.scheduled_start = starts
            appointment.scheduled_end = ends
            # A patient who agreed to Monday has not agreed to Thursday.
            appointment.status = SCHEDULED
            async with _refusing_clashes():
                await session.flush()
            await record_event(
                session,
                organization_id=organization_id,
                appointment=appointment,
                event=RESCHEDULED,
                from_status=before,
                actor_id=actor_id,
                detail=detail,
            )

    changed: list[str] = []
    for key, label in (
        ("appointment_type", "type"),
        ("source", "how it was booked"),
        ("reason", "reason"),
        ("notes", "notes"),
    ):
        if key not in supplied:
            continue
        value: Any = supplied[key]
        if key in ("appointment_type", "source") and value is None:
            continue
        value = value or None
        if getattr(appointment, key) != value:
            setattr(appointment, key, value)
            changed.append(label)

    if changed:
        await session.flush()
        await record_event(
            session,
            organization_id=organization_id,
            appointment=appointment,
            event=EDITED,
            from_status=appointment.status,
            actor_id=actor_id,
            detail=f"Changed the {_listed(changed)}.",
        )
    return appointment


def _listed(words: list[str]) -> str:
    if len(words) == 1:
        return words[0]
    return f"{', '.join(words[:-1])} and {words[-1]}"


async def confirm(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    appointment_id: uuid.UUID,
) -> Appointment:
    listed = await fetch(
        session,
        organization_id=organization_id,
        reach=reach,
        appointment_id=appointment_id,
        lock=True,
    )
    appointment = listed.appointment
    if appointment.status == CONFIRMED:
        raise InvalidTransition("This appointment is already confirmed.")
    _require_open(appointment)
    if appointment.scheduled_end <= clinic_now(clinic):
        raise InvalidTransition("This appointment has already happened.")

    appointment.status = CONFIRMED
    await session.flush()
    await record_event(
        session,
        organization_id=organization_id,
        appointment=appointment,
        event=CONFIRMED_EVENT,
        from_status=SCHEDULED,
        actor_id=actor_id,
    )
    return appointment


async def cancel(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    appointment_id: uuid.UUID,
    reason: str | None,
) -> Appointment:
    """Gives the slot back. Nothing is deleted: the history of who cancelled
    and why is worth more than the row it takes up."""
    listed = await fetch(
        session,
        organization_id=organization_id,
        reach=reach,
        appointment_id=appointment_id,
        lock=True,
    )
    appointment = listed.appointment
    _require_open(appointment)

    before = appointment.status
    appointment.status = CANCELLED
    appointment.cancelled_reason = reason or None
    appointment.cancelled_at = dt.datetime.now(dt.UTC)
    appointment.cancelled_by_id = actor_id
    await session.flush()
    await record_event(
        session,
        organization_id=organization_id,
        appointment=appointment,
        event=CANCELLED_EVENT,
        from_status=before,
        actor_id=actor_id,
        detail=reason or None,
    )
    return appointment


async def mark_no_show(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    appointment_id: uuid.UUID,
) -> Appointment:
    listed = await fetch(
        session,
        organization_id=organization_id,
        reach=reach,
        appointment_id=appointment_id,
        lock=True,
    )
    appointment = listed.appointment
    _require_open(appointment)
    # Nobody has failed to turn up for something that has not started.
    if appointment.scheduled_start > clinic_now(clinic):
        raise InvalidTransition("It has not started yet, so they have not missed it.")

    before = appointment.status
    appointment.status = NO_SHOW
    await session.flush()
    await record_event(
        session,
        organization_id=organization_id,
        appointment=appointment,
        event=MARKED_NO_SHOW,
        from_status=before,
        actor_id=actor_id,
    )
    return appointment


def present(
    listed: Listed,
    *,
    clinic: Organization,
    now: dt.datetime,
    booked_by_name: str | None = None,
    conflict: str | None = None,
    queue_token: int | None = None,
) -> dict[str, object]:
    appointment, patient, doctor = listed.appointment, listed.patient, listed.doctor
    zone = clinic_zone(clinic)
    starts = appointment.scheduled_start.astimezone(zone)
    ends = appointment.scheduled_end.astimezone(zone)

    if appointment.appointment_type == FOLLOW_UP:
        fee, _ = effective_fee(doctor.follow_up_fee, clinic, "follow_up_fee")
    else:
        fee, _ = effective_fee(doctor.consultation_fee, clinic, "consultation_fee")

    return {
        "id": appointment.id,
        "patient": {
            "id": patient.id,
            "patient_number": patient.patient_number,
            "full_name": patient.full_name,
            "preferred_name": patient.preferred_name,
            "phone": patient.phone,
            "age": age_label(patient.date_of_birth, now.date()),
            "gender": patient.gender,
            "status": patient.status,
            "allergy_count": listed.allergy_count,
        },
        "doctor": {
            "id": doctor.id,
            "display_name": doctor.display_name,
            "speciality": doctor.speciality,
            "room": doctor.room,
            "status": doctor.status,
        },
        "date": starts.date(),
        "start_time": starts.time(),
        "end_time": ends.time(),
        "scheduled_start": appointment.scheduled_start,
        "scheduled_end": appointment.scheduled_end,
        "appointment_type": appointment.appointment_type,
        "source": appointment.source,
        "status": appointment.status,
        "reason": appointment.reason,
        "notes": appointment.notes,
        "fee": fee,
        "cancelled_reason": appointment.cancelled_reason,
        "cancelled_at": appointment.cancelled_at,
        "booked_by_name": booked_by_name,
        "created_at": appointment.created_at,
        "has_started": appointment.scheduled_start <= now,
        "is_over": appointment.scheduled_end <= now,
        "is_today": starts.date() == now.date(),
        "conflict": conflict,
        "queue_token": queue_token,
    }


async def _conflicts(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    rows: list[Listed],
    now: dt.datetime,
) -> dict[uuid.UUID, str]:
    """Bookings the doctor's week no longer has room for.

    Leave is often taken after the appointments it lands on were made, and
    nothing moves them automatically — the desk has to ring those patients.
    Only open appointments still ahead are worth flagging.
    """
    zone = clinic_zone(clinic)
    plans: dict[tuple[uuid.UUID, dt.date], Any] = {}
    found: dict[uuid.UUID, str] = {}

    for row in rows:
        appointment = row.appointment
        if appointment.status not in OPEN or appointment.scheduled_end <= now:
            continue
        starts = appointment.scheduled_start.astimezone(zone)
        ends = appointment.scheduled_end.astimezone(zone)
        key = (row.doctor.id, starts.date())
        if key not in plans:
            plans[key] = await plan_day(
                session,
                organization_id=organization_id,
                clinic=clinic,
                doctor=row.doctor,
                day=starts.date(),
            )
        # A booking running past midnight cannot sit in one day's rota; it
        # is flagged rather than quietly passed.
        end_time = ends.time() if ends.date() == starts.date() else dt.time.max
        problem = plans[key].fits(starts.time(), end_time)
        if problem:
            found[appointment.id] = problem
    return found


async def _bookers(session: AsyncSession, rows: list[Listed]) -> dict[uuid.UUID, str]:
    return await names_of(
        session, {row.appointment.booked_by_id for row in rows if row.appointment.booked_by_id}
    )


async def present_all(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    rows: list[Listed],
    with_conflicts: bool = True,
) -> list[dict[str, object]]:
    now = clinic_now(clinic)
    names = await _bookers(session, rows)
    tokens = await QueueRepository(session, organization_id).for_appointments(
        {row.appointment.id for row in rows}
    )
    conflicts = (
        await _conflicts(
            session, organization_id=organization_id, clinic=clinic, rows=rows, now=now
        )
        if with_conflicts
        else {}
    )
    return [
        present(
            row,
            clinic=clinic,
            now=now,
            booked_by_name=names.get(row.appointment.booked_by_id)
            if row.appointment.booked_by_id
            else None,
            conflict=conflicts.get(row.appointment.id),
            queue_token=tokens.get(row.appointment.id),
        )
        for row in rows
    ]


async def day_list(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    day: dt.date,
    doctor_id: uuid.UUID | None,
) -> dict[str, object]:
    today = clinic_today(clinic)
    shape: dict[str, object] = {
        "date": day,
        "day_name": DAY_NAMES[day.weekday()],
        "is_today": day == today,
        "items": [],
        "only_doctor_id": reach.doctor_id if reach.narrowed else None,
        "unlinked": reach.unlinked,
    }
    if reach.unlinked:
        return shape

    opens_at, closes_at = day_bounds(clinic, day)
    rows = await AppointmentRepository(session, organization_id).between(
        opens_at,
        closes_at,
        doctor_id=reach.doctor_id if reach.narrowed else doctor_id,
    )
    shape["items"] = await present_all(
        session, organization_id=organization_id, clinic=clinic, rows=rows
    )
    return shape


async def for_patient(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    patient_id: uuid.UUID,
) -> dict[str, list[dict[str, object]]]:
    patient = await PatientRepository(session, organization_id).get(patient_id)
    if patient is None:
        raise PatientNotFound
    if reach.unlinked:
        return {"upcoming": [], "history": []}

    rows = await AppointmentRepository(session, organization_id).for_patient(
        patient_id, doctor_id=reach.doctor_id if reach.narrowed else None
    )
    now = clinic_now(clinic)
    ahead = [
        row
        for row in rows
        if row.appointment.status in OPEN and row.appointment.scheduled_end > now
    ]
    behind = [row for row in rows if row not in ahead][:HISTORY_SHOWN]
    ahead.reverse()

    return {
        "upcoming": await present_all(
            session, organization_id=organization_id, clinic=clinic, rows=ahead
        ),
        "history": await present_all(
            session,
            organization_id=organization_id,
            clinic=clinic,
            rows=behind,
            with_conflicts=False,
        ),
    }


async def detail(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    appointment_id: uuid.UUID,
) -> dict[str, object]:
    listed = await fetch(
        session, organization_id=organization_id, reach=reach, appointment_id=appointment_id
    )
    shaped = (
        await present_all(
            session, organization_id=organization_id, clinic=clinic, rows=[listed]
        )
    )[0]
    shaped["history"] = await EventRepository(session, organization_id).for_appointment(
        appointment_id
    )
    notes = await ConsultationRepository(session, organization_id).for_appointment(
        appointment_id
    )
    shaped["consultation_id"] = notes.id if notes else None
    return shaped
