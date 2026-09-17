"""Doctors, the week they sit, and working out who is free when.

Two things run through this file. A fee or a slot length left blank follows
the clinic's figure rather than freezing a copy of it, so raising the clinic
consultation fee reaches every doctor who never set their own. And
availability is worked out from the rota each time it is asked for, never
stored: a materialised slot table goes stale the moment a schedule changes,
and a stale slot table is how two people end up booked into one chair.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound, ValidationFailed
from app.models import Doctor, DoctorLeave, DoctorSchedule, Organization
from app.models.doctor import ACTIVE, DAY_NAMES, INACTIVE
from app.repositories.doctors import DoctorRepository, LeaveRepository, ScheduleRepository
from app.repositories.users import UserRepository
from app.schemas.doctor import (
    DoctorCreate,
    DoctorUpdate,
    LeaveWrite,
    ScheduleBlock,
    ScheduleWrite,
)

# Guards the slot loop against a block that somehow reached the database with
# a zero-length step. Schemas refuse it, the check constraint refuses it, and
# an infinite loop inside a request is worth one more line of defence.
FLOOR_SLOT_MINUTES = 5

# What a slot is when the clinic's own setting has been made unreadable.
DEFAULT_SLOT_MINUTES = 15


class DoctorNotFound(NotFound):
    code = "DOCTOR_NOT_FOUND"
    message = "That doctor could not be found."


class DoctorInactive(AppError):
    """Mirrors the way an archived patient refuses edits.

    A profile that has been stood down is a closed record. Bringing it back
    is one click, and is a decision somebody makes on purpose rather than
    discovers halfway through a form.
    """

    code = "DOCTOR_INACTIVE"
    status = 409
    message = "This doctor is not active. Restore them before making changes."


class RegistrationTaken(AppError):
    code = "REGISTRATION_NUMBER_TAKEN"
    status = 409
    message = "Another doctor at this clinic already has that registration number."


class AccountAlreadyLinked(AppError):
    code = "ACCOUNT_ALREADY_LINKED"
    status = 409
    message = "That account already belongs to another doctor."


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def clinic_today(clinic: Organization) -> dt.date:
    """The date it is at the clinic, not on the server.

    A clinic in Kolkata is already on tomorrow for five and a half hours of
    every UTC day, and "today" meaning yesterday is the sort of thing nobody
    notices until the morning list is empty.
    """
    try:
        zone: dt.tzinfo = ZoneInfo(clinic.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        # A clinic carrying a timezone this machine has never heard of gets
        # UTC rather than an error. Being an hour out beats a page that will
        # not load, and dt.UTC needs no database behind it.
        zone = dt.UTC
    return dt.datetime.now(zone).date()


def _money(value: Decimal | str | None) -> str:
    if value is None:
        return "0.00"
    try:
        return f"{Decimal(value):.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "0.00"


def clinic_fee(clinic: Organization, key: str) -> str:
    return _money(clinic.effective_settings.get(key))


def effective_fee(own: Decimal | None, clinic: Organization, key: str) -> tuple[str, bool]:
    """The figure that applies, and whether it came from the clinic.

    Zero is a real answer — plenty of clinics see staff families for nothing
    — so only an unset fee falls through to the clinic's.
    """
    if own is None:
        return clinic_fee(clinic, key), True
    return _money(own), False


def effective_slot_minutes(doctor: Doctor, clinic: Organization) -> int:
    if doctor.slot_duration_minutes:
        return doctor.slot_duration_minutes
    configured = clinic.effective_settings.get("consultation_duration_minutes")
    if not isinstance(configured, int | str):
        return DEFAULT_SLOT_MINUTES
    try:
        return max(int(configured), FLOOR_SLOT_MINUTES)
    except ValueError:
        return DEFAULT_SLOT_MINUTES


def block_slot_minutes(block: DoctorSchedule, doctor: Doctor, clinic: Organization) -> int:
    own = block.slot_duration_minutes or effective_slot_minutes(doctor, clinic)
    return max(own, FLOOR_SLOT_MINUTES)


def _overlap(
    one_start: dt.time, one_end: dt.time, two_start: dt.time, two_end: dt.time
) -> bool:
    """Half-open, so a block ending at 13:00 and one starting at 13:00 do not
    count as overlapping."""
    return one_start < two_end and two_start < one_end


def _minutes(value: dt.time) -> int:
    return value.hour * 60 + value.minute


def _at(minutes: int) -> dt.time:
    return dt.time(hour=minutes // 60, minute=minutes % 60)


def check_blocks(blocks: list[ScheduleBlock]) -> None:
    """Refuses a week that cannot be sat.

    The database holds each block to a sane shape; what it cannot see is the
    other blocks in the same submission, which is where the overlaps are.
    """
    problems: dict[str, str] = {}

    for index, block in enumerate(blocks):
        where = f"blocks.{index}"

        if block.end_time <= block.start_time:
            problems[f"{where}.end_time"] = "The end has to come after the start."
            continue

        if (block.break_start is None) != (block.break_end is None):
            problems[f"{where}.break_start"] = "Give the break a start and an end, or neither."
            continue

        if block.break_start and block.break_end:
            if block.break_end <= block.break_start:
                problems[f"{where}.break_end"] = "The break has to end after it starts."
                continue
            if block.break_start < block.start_time or block.break_end > block.end_time:
                problems[f"{where}.break_start"] = "The break has to sit inside these hours."
                continue

        length = _minutes(block.end_time) - _minutes(block.start_time)
        step = block.slot_duration_minutes or 0
        if step and length < step:
            problems[f"{where}.end_time"] = (
                f"That is shorter than one {step}-minute appointment."
            )

    if problems:
        raise ValidationFailed(problems)

    # Two blocks on one day that run into each other would put the doctor in
    # two rooms at once, and the slot list would hand out the same minute
    # twice. Checked across the whole submission, which is the only place
    # every block is visible at once.
    by_day: dict[int, list[tuple[int, ScheduleBlock]]] = {}
    for index, block in enumerate(blocks):
        by_day.setdefault(block.day_of_week, []).append((index, block))

    for day, same_day in by_day.items():
        ordered = sorted(same_day, key=lambda pair: pair[1].start_time)
        for (_, earlier), (index, later) in pairwise(ordered):
            if _overlap(earlier.start_time, earlier.end_time, later.start_time, later.end_time):
                problems[f"blocks.{index}.start_time"] = (
                    f"This overlaps another {DAY_NAMES[day]} block."
                )

    if problems:
        raise ValidationFailed(problems)


def check_leave(body: LeaveWrite) -> dt.date:
    """Returns the last day, filled in from the first when it was left out."""
    ends_on = body.ends_on or body.starts_on
    problems: dict[str, str] = {}

    if ends_on < body.starts_on:
        problems["ends_on"] = "Leave cannot end before it starts."
    if (body.start_time is None) != (body.end_time is None):
        problems["start_time"] = "Give the times as a pair, or leave both blank for whole days."
    elif body.start_time and body.end_time and body.end_time <= body.start_time:
        problems["end_time"] = "The end has to come after the start."

    if problems:
        raise ValidationFailed(problems)
    return ends_on


async def _resolve_account(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    exclude_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    if user_id is None:
        return None

    account = await UserRepository(session).get(user_id)
    # Somebody else's staff member reads as a field that does not match
    # anyone, never as confirmation that the account exists elsewhere.
    if account is None or account.organization_id != organization_id:
        raise ValidationFailed({"user_id": "That is not somebody at this clinic."})

    if await DoctorRepository(session, organization_id).linked_to(user_id, exclude_id):
        raise AccountAlreadyLinked
    return user_id


async def _check_registration(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    number: str | None,
    exclude_id: uuid.UUID | None = None,
) -> None:
    if not number:
        return
    taken = await DoctorRepository(session, organization_id).registered_as(number, exclude_id)
    if taken is not None:
        raise RegistrationTaken


async def add(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    body: DoctorCreate,
) -> Doctor:
    await _check_registration(
        session, organization_id=organization_id, number=body.registration_number
    )
    user_id = await _resolve_account(
        session, organization_id=organization_id, user_id=body.user_id
    )

    doctor = Doctor(
        user_id=user_id,
        title=body.title,
        first_name=body.first_name,
        last_name=body.last_name,
        speciality=body.speciality or None,
        qualifications=body.qualifications or None,
        registration_number=body.registration_number or None,
        years_of_experience=body.years_of_experience,
        phone=body.phone,
        email=body.email,
        room=body.room or None,
        languages=body.languages,
        bio=body.bio or None,
        consultation_fee=body.consultation_fee,
        follow_up_fee=body.follow_up_fee,
        slot_duration_minutes=body.slot_duration_minutes,
        status=ACTIVE,
    )
    # Stamped by the repository, never taken from the request body.
    await DoctorRepository(session, organization_id).add(doctor)
    return doctor


async def fetch(
    session: AsyncSession, *, organization_id: uuid.UUID, doctor_id: uuid.UUID
) -> Doctor:
    doctor = await DoctorRepository(session, organization_id).get(doctor_id)
    if doctor is None:
        raise DoctorNotFound
    return doctor


async def update(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    doctor_id: uuid.UUID,
    body: DoctorUpdate,
) -> Doctor:
    doctor = await fetch(session, organization_id=organization_id, doctor_id=doctor_id)
    if not doctor.is_active:
        raise DoctorInactive

    supplied = body.model_dump(exclude_unset=True)

    if "registration_number" in supplied:
        await _check_registration(
            session,
            organization_id=organization_id,
            number=supplied["registration_number"],
            exclude_id=doctor_id,
        )
    if "user_id" in supplied:
        supplied["user_id"] = await _resolve_account(
            session,
            organization_id=organization_id,
            user_id=supplied["user_id"],
            exclude_id=doctor_id,
        )
    if "last_name" in supplied and supplied["last_name"] is None:
        # The column is not nullable; clearing a surname means blank.
        supplied["last_name"] = ""

    for field, value in supplied.items():
        setattr(doctor, field, value)

    await session.flush()
    return doctor


async def set_active(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    doctor_id: uuid.UUID,
    active: bool,
) -> Doctor:
    """Stands a doctor down without losing anything attached to them.

    Their rota stays exactly as it was, so bringing back a consultant who
    was away for six months does not mean typing the week out again.
    """
    doctor = await fetch(session, organization_id=organization_id, doctor_id=doctor_id)
    doctor.status = ACTIVE if active else INACTIVE
    doctor.deactivated_at = None if active else _now()
    await session.flush()
    return doctor


async def replace_schedule(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    doctor_id: uuid.UUID,
    body: ScheduleWrite,
) -> list[DoctorSchedule]:
    doctor = await fetch(session, organization_id=organization_id, doctor_id=doctor_id)
    if not doctor.is_active:
        raise DoctorInactive

    check_blocks(body.blocks)

    schedules = ScheduleRepository(session, organization_id)
    # Cleared and rewritten inside the request's transaction, so a reader
    # never sees half a week and a failure leaves the old one in place.
    await schedules.clear(doctor_id)
    for block in body.blocks:
        await schedules.add(
            DoctorSchedule(
                doctor_id=doctor_id,
                day_of_week=block.day_of_week,
                start_time=block.start_time,
                end_time=block.end_time,
                break_start=block.break_start,
                break_end=block.break_end,
                slot_duration_minutes=block.slot_duration_minutes,
            )
        )
    return await schedules.for_doctor(doctor_id)


async def add_leave(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    doctor_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: LeaveWrite,
) -> DoctorLeave:
    doctor = await fetch(session, organization_id=organization_id, doctor_id=doctor_id)
    if not doctor.is_active:
        raise DoctorInactive

    ends_on = check_leave(body)

    leave = DoctorLeave(
        doctor_id=doctor_id,
        starts_on=body.starts_on,
        ends_on=ends_on,
        start_time=body.start_time,
        end_time=body.end_time,
        reason=body.reason or None,
        recorded_by_id=actor_id,
    )
    await LeaveRepository(session, organization_id).add(leave)
    return leave


async def remove_leave(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    doctor_id: uuid.UUID,
    leave_id: uuid.UUID,
) -> None:
    leaves = LeaveRepository(session, organization_id)
    leave = await leaves.belonging_to(doctor_id, leave_id)
    if leave is None:
        raise NotFound("That leave could not be found.")

    await session.delete(leave)
    await session.flush()


def describe_leave(leave: DoctorLeave, day: dt.date) -> str:
    """The sentence the screen shows in place of a list of times."""
    reason = f" — {leave.reason}" if leave.reason else ""
    if leave.ends_on == day:
        return f"On leave today{reason}"

    written = f"{leave.ends_on.day} {leave.ends_on.strftime('%B')}"
    if leave.ends_on.year != day.year:
        written = f"{written} {leave.ends_on.year}"
    return f"On leave until {written}{reason}"


async def availability(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    doctor_id: uuid.UUID,
    day: dt.date,
) -> dict[str, object]:
    """One day of a doctor's rota, minus their break and minus their leave."""
    doctor = await fetch(session, organization_id=organization_id, doctor_id=doctor_id)
    day_of_week = day.weekday()
    minutes = effective_slot_minutes(doctor, clinic)

    empty: dict[str, object] = {
        "date": day,
        "day_of_week": day_of_week,
        "day_name": DAY_NAMES[day_of_week],
        "working": False,
        "reason": None,
        "slot_duration_minutes": minutes,
        "slots": [],
    }

    if not doctor.is_active:
        empty["reason"] = "Not seeing patients at the moment."
        return empty

    blocks = await ScheduleRepository(session, organization_id).on_day(doctor_id, day_of_week)
    if not blocks:
        empty["reason"] = f"No {DAY_NAMES[day_of_week]} clinic."
        return empty

    leaves = await LeaveRepository(session, organization_id).covering(doctor_id, day)
    whole_day = next((leave for leave in leaves if leave.is_all_day), None)
    if whole_day is not None:
        empty["reason"] = describe_leave(whole_day, day)
        return empty

    # A timed leave spanning several days means those hours on each of them,
    # which is how somebody describes leaving early all week.
    away = [
        (leave.start_time, leave.end_time)
        for leave in leaves
        if leave.start_time and leave.end_time
    ]

    slots: list[dict[str, dt.time]] = []
    for block in blocks:
        step = block_slot_minutes(block, doctor, clinic)
        start = _minutes(block.start_time)
        finish = _minutes(block.end_time)

        while start + step <= finish:
            opens, closes = _at(start), _at(start + step)
            start += step

            if (
                block.break_start
                and block.break_end
                and _overlap(opens, closes, block.break_start, block.break_end)
            ):
                continue
            if any(_overlap(opens, closes, begins, ends) for begins, ends in away):
                continue

            slots.append({"start_time": opens, "end_time": closes})

    return {
        "date": day,
        "day_of_week": day_of_week,
        "day_name": DAY_NAMES[day_of_week],
        "working": bool(slots),
        "reason": None if slots else "Away for the whole of this clinic.",
        "slot_duration_minutes": minutes,
        "slots": slots,
    }
