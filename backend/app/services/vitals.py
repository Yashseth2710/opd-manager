"""Vital signs: taken for a place in the queue, corrected on the day.

Whoever can take them can put right a slip on the same day, until the visit
is finished. After that they are part of what the doctor saw and decided
on, and stay as they were.

What counts as out of range is worked out here rather than stored, so the
same reading reads the same on every screen. Blood pressure, pulse,
breathing and BMI are judged against adult ranges and only for adults: a
child's normal depends on their age, and flagging a healthy four-year-old's
pulse as high would teach everyone to ignore the flag.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound, ValidationFailed
from app.models import Organization, Patient, QueueEntry, Vitals
from app.models import queue as line
from app.models import vitals as measured
from app.repositories.queue import QueueRepository
from app.repositories.vitals import Taken, VitalsRepository
from app.schemas.vitals import Readings
from app.services.appointments import Reach, spoken_day
from app.services.doctors import clinic_now, clinic_today
from app.services.patients import age_in_years

ADULT = 18


class VitalsNotFound(NotFound):
    code = "VITALS_NOT_FOUND"
    message = "Those vital signs could not be found."


class AlreadyTaken(AppError):
    code = "VITALS_ALREADY_TAKEN"
    status = 409
    message = "Vital signs have already been taken for this visit. Correct those instead."


class VitalsLocked(AppError):
    code = "VITALS_LOCKED"
    status = 409
    message = "These vital signs can no longer be changed."


# --- Reading them ------------------------------------------------------------


def _bmi(weight_kg: Decimal | None, height_cm: Decimal | None) -> float | None:
    if weight_kg is None or height_cm is None:
        return None
    metres = float(height_cm) / 100
    return round(float(weight_kg) / (metres * metres), 1)


def _bmi_band(bmi: float) -> str:
    # The cut-offs agreed for Indian adults, lower than the WHO's because
    # the risk that goes with weight starts sooner.
    if bmi < 18.5:
        return "underweight"
    if bmi < 23:
        return "normal"
    if bmi < 25:
        return "overweight"
    return "obese"


def assess(vitals: Vitals, age: int | None) -> dict[str, Any]:
    """The BMI where it means something, and each reading outside its range."""
    flags: dict[str, str] = {}
    adult = age is not None and age >= ADULT

    if vitals.temperature_c is not None:
        if vitals.temperature_c >= Decimal("37.5"):
            flags["temperature"] = "high"
        elif vitals.temperature_c < 35:
            flags["temperature"] = "low"
    if vitals.spo2_percent is not None and vitals.spo2_percent < 95:
        flags["spo2"] = "low"
    if vitals.glucose_mg_dl is not None:
        ceiling = {
            measured.FASTING: 126,
            measured.AFTER_MEAL: 140,
            measured.RANDOM: 200,
        }.get(vitals.glucose_timing or measured.RANDOM, 200)
        if vitals.glucose_mg_dl >= ceiling:
            flags["glucose"] = "high"
        elif vitals.glucose_mg_dl < 70:
            flags["glucose"] = "low"

    bmi = band = None
    if adult:
        systolic, diastolic = vitals.systolic_mmhg, vitals.diastolic_mmhg
        if systolic is not None and diastolic is not None:
            if systolic >= 140 or diastolic >= 90:
                flags["blood_pressure"] = "high"
            elif systolic < 90 or diastolic < 60:
                flags["blood_pressure"] = "low"
        if vitals.pulse_bpm is not None:
            if vitals.pulse_bpm > 100:
                flags["pulse"] = "high"
            elif vitals.pulse_bpm < 60:
                flags["pulse"] = "low"
        if vitals.respiratory_rate is not None:
            if vitals.respiratory_rate > 20:
                flags["respiratory_rate"] = "high"
            elif vitals.respiratory_rate < 12:
                flags["respiratory_rate"] = "low"
        bmi = _bmi(vitals.weight_kg, vitals.height_cm)
        if bmi is not None:
            band = _bmi_band(bmi)
            if band == "underweight":
                flags["bmi"] = "low"
            elif band in ("overweight", "obese"):
                flags["bmi"] = "high"

    return {"bmi": bmi, "bmi_band": band, "flags": flags}


def _age(patient: Patient, on: dt.date) -> int | None:
    return age_in_years(patient.date_of_birth, on)


def _changeable(vitals: Vitals, entry: QueueEntry, today: dt.date) -> str | None:
    """Why these can no longer be changed, or nothing if they can."""
    if entry.status == line.COMPLETED:
        return "The visit is finished, so these vital signs are part of its record now."
    if entry.status == line.NO_SHOW:
        return "They have been marked as gone, so these vital signs are closed."
    if vitals.taken_on != today:
        return (
            f"These were taken on {spoken_day(vitals.taken_on, beside=today)}, "
            "and can only be changed on the day."
        )
    return None


def present(taken: Taken, *, today: dt.date, may_record: bool, reach: Reach) -> dict[str, Any]:
    vitals = taken.vitals
    return {
        "id": vitals.id,
        "patient_id": vitals.patient_id,
        "queue_entry_id": vitals.queue_entry_id,
        "systolic_mmhg": vitals.systolic_mmhg,
        "diastolic_mmhg": vitals.diastolic_mmhg,
        "pulse_bpm": vitals.pulse_bpm,
        "temperature_c": vitals.temperature_c,
        "spo2_percent": vitals.spo2_percent,
        "respiratory_rate": vitals.respiratory_rate,
        "weight_kg": vitals.weight_kg,
        "height_cm": vitals.height_cm,
        "glucose_mg_dl": vitals.glucose_mg_dl,
        "glucose_timing": vitals.glucose_timing,
        "note": vitals.note,
        **assess(vitals, _age(taken.patient, vitals.taken_on)),
        "taken_at": vitals.taken_at,
        "taken_on": vitals.taken_on,
        "taken_by": taken.taken_by,
        "changed_by": taken.changed_by,
        "updated_at": vitals.updated_at,
        "can_change": may_record
        and reach.covers(taken.entry.doctor_id)
        and _changeable(vitals, taken.entry, today) is None,
    }


# --- Taking them ---------------------------------------------------------------


def _places(value: Decimal | None, step: str) -> Decimal | None:
    return None if value is None else value.quantize(Decimal(step), rounding=ROUND_HALF_UP)


def _checked(readings: Readings) -> dict[str, Any]:
    """The readings as they will be kept, or the reason they cannot be."""
    sugar = readings.glucose_mg_dl
    values: dict[str, Any] = {
        "systolic_mmhg": readings.systolic_mmhg,
        "diastolic_mmhg": readings.diastolic_mmhg,
        "pulse_bpm": readings.pulse_bpm,
        "temperature_c": _places(readings.temperature_c, "0.01"),
        "spo2_percent": readings.spo2_percent,
        "respiratory_rate": readings.respiratory_rate,
        "weight_kg": _places(readings.weight_kg, "0.01"),
        "height_cm": _places(readings.height_cm, "0.1"),
        "glucose_mg_dl": sugar,
        # When a sugar was taken means nothing without the sugar.
        "glucose_timing": readings.glucose_timing if sugar is not None else None,
        "note": readings.note or None,
    }

    fields: dict[str, str] = {}
    systolic, diastolic = values["systolic_mmhg"], values["diastolic_mmhg"]
    if systolic is None and diastolic is not None:
        fields["systolic_mmhg"] = "Enter the upper number as well."
    elif diastolic is None and systolic is not None:
        fields["diastolic_mmhg"] = "Enter the lower number as well."
    elif systolic is not None and diastolic is not None and diastolic >= systolic:
        fields["diastolic_mmhg"] = "The lower number has to be below the upper one."
    if values["glucose_mg_dl"] is not None and values["glucose_timing"] is None:
        fields["glucose_timing"] = "Say when the sugar was taken."
    if fields:
        raise ValidationFailed(fields)

    if all(values[column] is None for column in measured.MEASURES):
        raise ValidationFailed(
            {"readings": "Enter at least one reading."}, "Enter at least one reading."
        )
    return values


async def _place(
    session: AsyncSession,
    organization_id: uuid.UUID,
    reach: Reach,
    entry_id: uuid.UUID,
    today: dt.date,
) -> QueueEntry:
    """The place the readings are for, locked, and still open for them."""
    found = await QueueRepository(session, organization_id).one(entry_id, lock=True)
    # Outside a doctor's own line reads as absent, as it does in the queue.
    if found is None or not reach.covers(found.doctor.id):
        raise ValidationFailed({"queue_entry_id": "That patient is not in the queue."})
    entry = found.entry
    if entry.token_date != today:
        raise VitalsLocked(
            f"This place was in the queue on {spoken_day(entry.token_date, beside=today)}."
        )
    if entry.status == line.COMPLETED:
        raise VitalsLocked("They have already been seen, so the visit is closed.")
    if entry.status == line.NO_SHOW:
        raise VitalsLocked("They have been marked as gone.")
    return entry


async def take(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    entry_id: uuid.UUID,
    readings: Readings,
) -> uuid.UUID:
    values = _checked(readings)
    today = clinic_today(clinic)
    entry = await _place(session, organization_id, reach, entry_id, today)
    repository = VitalsRepository(session, organization_id)
    # The place is locked, so a second desk taking them at the same moment
    # waits here and then finds the first set.
    if await repository.for_entry(entry.id) is not None:
        raise AlreadyTaken
    vitals = await repository.add(
        Vitals(
            patient_id=entry.patient_id,
            queue_entry_id=entry.id,
            taken_at=clinic_now(clinic),
            taken_on=today,
            taken_by_id=actor_id,
            **values,
        )
    )
    return vitals.id


async def _open(
    session: AsyncSession,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    vitals_id: uuid.UUID,
) -> Vitals:
    repository = VitalsRepository(session, organization_id)
    found = await repository.one(vitals_id)
    if found is None or not reach.covers(found.entry.doctor_id):
        raise VitalsNotFound
    # The place first and then the readings, the order taking them uses, so
    # the two never wait on each other.
    await QueueRepository(session, organization_id).one(found.entry.id, lock=True)
    locked = await repository.one(vitals_id, lock=True)
    if locked is None:
        raise VitalsNotFound
    why = _changeable(locked.vitals, locked.entry, clinic_today(clinic))
    if why is not None:
        raise VitalsLocked(why)
    return locked.vitals


async def change(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    actor_id: uuid.UUID,
    vitals_id: uuid.UUID,
    readings: Readings,
) -> None:
    values = _checked(readings)
    vitals = await _open(session, organization_id, clinic, reach, vitals_id)
    for column, value in values.items():
        setattr(vitals, column, value)
    vitals.changed_by_id = actor_id
    await session.flush()


async def remove(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    vitals_id: uuid.UUID,
) -> None:
    vitals = await _open(session, organization_id, clinic, reach, vitals_id)
    await session.delete(vitals)
    await session.flush()


# --- Handing them back ------------------------------------------------------------


async def one(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    may_record: bool,
    vitals_id: uuid.UUID,
) -> dict[str, Any]:
    found = await VitalsRepository(session, organization_id).one(vitals_id)
    if found is None:
        raise VitalsNotFound
    return present(found, today=clinic_today(clinic), may_record=may_record, reach=reach)


async def for_entry(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    may_record: bool,
    entry_id: uuid.UUID,
) -> dict[str, Any] | None:
    found = await VitalsRepository(session, organization_id).for_entry(entry_id)
    if found is None:
        return None
    return present(found, today=clinic_today(clinic), may_record=may_record, reach=reach)


async def for_patient(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    may_record: bool,
    patient_id: uuid.UUID,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    found, total = await VitalsRepository(session, organization_id).for_patient(
        patient_id, limit=limit, offset=offset
    )
    today = clinic_today(clinic)
    return {
        "items": [
            present(taken, today=today, may_record=may_record, reach=reach) for taken in found
        ],
        "total": total,
    }
