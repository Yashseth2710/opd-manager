"""Registering and maintaining patient records.

Two rules run through this file. A record is never deleted, only archived,
because the history hanging off it outlives any reason to hide it. And a
suspected duplicate is surfaced, never resolved: splitting one person across
two records is bad, and merging two people into one is worse.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound, ValidationFailed
from app.models.counter import PATIENT
from app.models.patient import ACTIVE, ARCHIVED, NUMBER_PREFIX, Patient, PatientAllergy
from app.repositories.counters import next_in_sequence
from app.repositories.patients import AllergyRepository, Listed, PatientRepository
from app.schemas.patient import AllergyWrite, PatientCreate, PatientUpdate

# Long enough that a clinic seeing a hundred people a day never rolls over,
# short enough to read down a phone line.
NUMBER_WIDTH = 6

OLDEST_PLAUSIBLE_YEARS = 130
PHONE_DIGITS = range(7, 16)


class PatientNotFound(NotFound):
    code = "PATIENT_NOT_FOUND"
    message = "That patient could not be found."


class PatientArchived(AppError):
    code = "PATIENT_ARCHIVED"
    status = 409
    message = "This record is archived. Restore it before making changes."


class DuplicateSuspected(AppError):
    """Not a refusal so much as a question.

    The person at the desk is the only one who can tell whether two records
    with the same phone number are one family sharing a handset or somebody
    being registered twice.
    """

    code = "PATIENT_DUPLICATE_SUSPECTED"
    status = 409
    message = "Somebody with these details is already registered."

    def __init__(self, candidates: list[dict[str, object]]) -> None:
        super().__init__()
        self.candidates = candidates


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def age_label(date_of_birth: dt.date | None, today: dt.date | None = None) -> str | None:
    """Age written the way it is said out loud.

    Infants are described in days and months because a doctor dosing a
    six-week-old needs that precision, and "0 y" is no use to anybody.
    """
    if date_of_birth is None:
        return None

    now = today or dt.date.today()
    if date_of_birth > now:
        return None

    months = (now.year - date_of_birth.year) * 12 + (now.month - date_of_birth.month)
    if now.day < date_of_birth.day:
        months -= 1

    if months < 1:
        return f"{(now - date_of_birth).days} d"
    if months < 24:
        return f"{months} mo"
    return f"{months // 12} y"


def age_in_years(date_of_birth: dt.date | None, today: dt.date | None = None) -> int | None:
    if date_of_birth is None:
        return None
    now = today or dt.date.today()
    years = now.year - date_of_birth.year
    if (now.month, now.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return max(years, 0)


def _check(
    *,
    date_of_birth: dt.date | None,
    phone: str | None,
    alternate_phone: str | None,
) -> None:
    problems: dict[str, str] = {}

    if date_of_birth is not None:
        today = dt.date.today()
        if date_of_birth > today:
            problems["date_of_birth"] = "Date of birth cannot be in the future."
        elif date_of_birth.year < today.year - OLDEST_PLAUSIBLE_YEARS:
            problems["date_of_birth"] = "Check the year — that date is not plausible."

    for field, value in (("phone", phone), ("alternate_phone", alternate_phone)):
        if value and len(value.lstrip("+")) not in PHONE_DIGITS:
            problems[field] = "Enter a phone number with 7 to 15 digits."

    if problems:
        raise ValidationFailed(problems)


def candidate_reason(patient: Patient, *, phone: str | None, email: str | None) -> str:
    if phone and phone in {patient.phone, patient.alternate_phone}:
        return "Same phone number"
    if email and patient.email and patient.email.lower() == email.lower():
        return "Same email address"
    return "Same name and date of birth"


def describe_candidates(
    found: list[Listed], *, phone: str | None, email: str | None
) -> list[dict[str, object]]:
    """Shaped for the error body, which is plain JSON by the time it reaches
    the handler that renders it.

    Carries the same fields as a row in the patient list plus the reason it
    surfaced, so the screen showing it can reuse the same component. A test
    holds the two shapes in step.
    """
    return [
        {
            "id": str(row.patient.id),
            "patient_number": row.patient.patient_number,
            "full_name": row.patient.full_name,
            "preferred_name": row.patient.preferred_name,
            "phone": row.patient.phone,
            "date_of_birth": row.patient.date_of_birth.isoformat()
            if row.patient.date_of_birth
            else None,
            "age": age_label(row.patient.date_of_birth),
            "gender": row.patient.gender,
            "blood_group": row.patient.blood_group,
            "status": row.patient.status,
            "allergy_count": row.allergy_count,
            "created_at": row.patient.created_at.isoformat(),
            "reason": candidate_reason(row.patient, phone=phone, email=email),
        }
        for row in found
    ]


async def next_patient_number(session: AsyncSession, organization_id: uuid.UUID) -> str:
    sequence = await next_in_sequence(session, organization_id, PATIENT)
    return f"{NUMBER_PREFIX}-{sequence:0{NUMBER_WIDTH}d}"


async def register(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: PatientCreate,
) -> Patient:
    _check(
        date_of_birth=body.date_of_birth,
        phone=body.phone,
        alternate_phone=body.alternate_phone,
    )

    patients = PatientRepository(session, organization_id)

    if not body.confirm_duplicate:
        found = await patients.possible_duplicates(
            first_name=body.first_name,
            last_name=body.last_name,
            phone=body.phone,
            email=body.email,
            date_of_birth=body.date_of_birth,
        )
        if found:
            raise DuplicateSuspected(
                describe_candidates(found, phone=body.phone, email=body.email)
            )

    patient = Patient(
        patient_number=await next_patient_number(session, organization_id),
        first_name=body.first_name,
        last_name=body.last_name,
        preferred_name=body.preferred_name or None,
        phone=body.phone,
        alternate_phone=body.alternate_phone,
        email=body.email,
        date_of_birth=body.date_of_birth,
        gender=body.gender,
        blood_group=body.blood_group,
        address=body.address.model_dump() if body.address else None,
        emergency_contact=body.emergency_contact.model_dump()
        if body.emergency_contact
        else None,
        notes=body.notes or None,
        status=ACTIVE,
        registered_by_id=actor_id,
    )
    # Stamped by the repository, never taken from the request body.
    await patients.add(patient)
    return patient


async def fetch(
    session: AsyncSession, *, organization_id: uuid.UUID, patient_id: uuid.UUID
) -> Listed:
    found = await PatientRepository(session, organization_id).with_allergy_count(patient_id)
    # Another clinic's record reads as absent, never as forbidden.
    if found is None:
        raise PatientNotFound
    return found


async def update(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    patient_id: uuid.UUID,
    body: PatientUpdate,
) -> Patient:
    patients = PatientRepository(session, organization_id)
    patient = await patients.get(patient_id)
    if patient is None:
        raise PatientNotFound
    if patient.is_archived:
        raise PatientArchived

    supplied = body.model_dump(exclude_unset=True)

    _check(
        date_of_birth=supplied.get("date_of_birth", patient.date_of_birth),
        phone=supplied.get("phone", patient.phone),
        alternate_phone=supplied.get("alternate_phone", patient.alternate_phone),
    )

    for field in ("address", "emergency_contact"):
        if field in supplied and supplied[field] is not None:
            # Replaced whole rather than merged. A half-updated address is
            # harder to spot than a wrong one.
            setattr(patient, field, dict(supplied.pop(field)))
        elif field in supplied:
            setattr(patient, field, None)
            supplied.pop(field)

    for field, value in supplied.items():
        setattr(patient, field, value)

    await session.flush()
    return patient


async def set_archived(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    patient_id: uuid.UUID,
    archived: bool,
) -> Patient:
    patients = PatientRepository(session, organization_id)
    patient = await patients.get(patient_id)
    if patient is None:
        raise PatientNotFound

    patient.status = ARCHIVED if archived else ACTIVE
    patient.archived_at = _now() if archived else None
    await session.flush()
    return patient


async def add_allergy(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    patient_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: AllergyWrite,
) -> PatientAllergy:
    patient = await PatientRepository(session, organization_id).get(patient_id)
    if patient is None:
        raise PatientNotFound
    if patient.is_archived:
        raise PatientArchived

    allergies = AllergyRepository(session, organization_id)
    existing = await allergies.for_patient(patient_id)
    if any(row.substance.lower() == body.substance.lower() for row in existing):
        raise ValidationFailed({"substance": "That is already on this patient's list."})

    allergy = PatientAllergy(
        patient_id=patient_id,
        substance=body.substance,
        reaction=body.reaction or None,
        severity=body.severity,
        recorded_by_id=actor_id,
    )
    await allergies.add(allergy)
    return allergy


async def remove_allergy(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    patient_id: uuid.UUID,
    allergy_id: uuid.UUID,
) -> None:
    allergies = AllergyRepository(session, organization_id)
    allergy = await allergies.belonging_to(patient_id, allergy_id)
    if allergy is None:
        raise NotFound("That allergy could not be found.")

    await session.delete(allergy)
    await session.flush()
