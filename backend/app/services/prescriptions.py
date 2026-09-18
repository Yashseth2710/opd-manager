"""Prescriptions: written with the notes, issued when the visit is finished.

While the visit is open the doctor's lines sit in a draft that only the
notes screen shows. Finishing the visit issues it: it gets the clinic's next
number and is fixed from then on. A mistake is put right with a correction,
which issues a new prescription and marks the old one replaced, so the paper
a pharmacy already has can still be matched to what the clinic holds.

Anyone at the clinic whose role reads prescriptions can read every issued
one, since the desk prints and hands them over. Only the doctor who wrote a
prescription corrects it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound, ValidationFailed
from app.models import Consultation, Organization, Prescription
from app.models import prescription as rx
from app.models.counter import PRESCRIPTION
from app.repositories.counters import next_in_sequence
from app.repositories.prescriptions import PrescriptionRepository, Written
from app.schemas.prescription import MedicineLine
from app.services.appointments import Reach
from app.services.doctors import clinic_today, clinic_zone
from app.services.patients import age_label


class PrescriptionNotFound(NotFound):
    code = "RX_NOT_FOUND"
    message = "That prescription could not be found."


class AlreadyReplaced(AppError):
    code = "RX_ALREADY_REPLACED"
    status = 409
    message = "This prescription has already been replaced."


class NotPrescriber(AppError):
    code = "RX_NOT_PRESCRIBER"
    status = 403
    message = "Only the doctor who wrote this prescription can correct it."


def _number(sequence: int) -> str:
    return f"RX-{sequence:06d}"


def _blank(value: str | None) -> str | None:
    return value if value else None


def _line(line: MedicineLine) -> dict[str, Any]:
    return {
        "medicine_name": line.medicine_name,
        "presentation": _blank(line.presentation),
        "dose": _blank(line.dose),
        "timing": line.timing,
        "duration_days": line.duration_days,
        "instructions": _blank(line.instructions),
    }


def _refuse_incomplete(lines: list[dict[str, Any]], prefix: str = "medicines") -> None:
    """A dose is the one thing a line cannot be issued without."""
    missing = {
        f"{prefix}.{index}.dose": "Say how much to take."
        for index, line in enumerate(lines)
        if not line["dose"]
    }
    if missing:
        first = next(iter(missing))
        position = int(first.split(".")[1]) + 1
        raise ValidationFailed(
            missing,
            f"Medicine {position} on the prescription has no dose yet.",
        )


# --- The draft, written with the notes -----------------------------------------


async def write_draft(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    consultation: Consultation,
    lines: list[MedicineLine] | None,
    instructions: str | None,
    sent_lines: bool,
    sent_instructions: bool,
) -> None:
    """Keeps the draft in step with the notes screen. The caller holds the
    lock on the consultation, so two saves never race to make a draft."""
    repository = PrescriptionRepository(session, organization_id)
    draft = await repository.draft_for(consultation.id)
    if draft is None:
        draft = await repository.add(
            Prescription(
                consultation_id=consultation.id,
                patient_id=consultation.patient_id,
                doctor_id=consultation.doctor_id,
                status=rx.DRAFT,
            )
        )
    if sent_instructions:
        draft.instructions = _blank(instructions)
    if sent_lines:
        await repository.replace_items(draft.id, [_line(line) for line in lines or []])
    await session.flush()


async def ready_to_issue(
    session: AsyncSession, *, organization_id: uuid.UUID, consultation: Consultation
) -> Prescription | None:
    """The draft this visit will issue, checked, or nothing if nothing was
    written. An empty draft is removed rather than issued as a blank."""
    repository = PrescriptionRepository(session, organization_id)
    draft = await repository.draft_for(consultation.id)
    if draft is None:
        return None
    items = await repository.items_of(draft.id)
    if not items and not draft.instructions:
        await session.delete(draft)
        await session.flush()
        return None
    _refuse_incomplete(
        [{"dose": item.dose} for item in items],
    )
    return draft


async def issue(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    prescription: Prescription,
    follow_up_date: dt.date | None,
    actor_id: uuid.UUID,
) -> None:
    sequence = await next_in_sequence(session, organization_id, PRESCRIPTION)
    prescription.prescription_number = _number(sequence)
    prescription.status = rx.ISSUED
    prescription.issued_at = dt.datetime.now(dt.UTC)
    prescription.issued_by_id = actor_id
    prescription.follow_up_date = follow_up_date
    await session.flush()


# --- Corrections -----------------------------------------------------------


async def correct(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    prescription_id: uuid.UUID,
    lines: list[MedicineLine],
    instructions: str | None,
    reason: str,
) -> Prescription:
    repository = PrescriptionRepository(session, organization_id)
    found = await repository.one(prescription_id, lock=True)
    if found is None or found.prescription.is_draft:
        raise PrescriptionNotFound
    original = found.prescription
    if not (reach.narrowed and reach.doctor_id == original.doctor_id):
        raise NotPrescriber(
            f"This prescription is {found.doctor.display_name}'s. Only they can correct it."
        )
    if original.status == rx.REPLACED:
        newer = (await repository.replacing({original.id})).get(original.id)
        raise AlreadyReplaced(
            f"{original.prescription_number} has already been replaced"
            + (f" by {newer[1]}." if newer else ".")
            + " Correct the newer one instead."
        )

    written = [_line(line) for line in lines]
    _refuse_incomplete(written)

    # Stood down first: the database allows one standing prescription per
    # visit, and the correction is about to become it.
    original.status = rx.REPLACED
    await session.flush()

    replacement = await repository.add(
        Prescription(
            consultation_id=original.consultation_id,
            patient_id=original.patient_id,
            doctor_id=original.doctor_id,
            status=rx.DRAFT,
            instructions=_blank(instructions),
            replaces_id=original.id,
            correction_reason=reason,
        )
    )
    await repository.replace_items(replacement.id, written)
    await issue(
        session,
        organization_id=organization_id,
        prescription=replacement,
        follow_up_date=original.follow_up_date,
        actor_id=actor_id,
    )
    return replacement


# --- Reading ---------------------------------------------------------------


def _items(written: Written) -> list[dict[str, Any]]:
    return [
        {
            "medicine_name": item.medicine_name,
            "presentation": item.presentation,
            "dose": item.dose,
            "timing": item.timing,
            "duration_days": item.duration_days,
            "instructions": item.instructions,
        }
        for item in written.items
    ]


async def _links(
    repository: PrescriptionRepository, found: list[Written]
) -> tuple[dict[uuid.UUID, str | None], dict[uuid.UUID, tuple[uuid.UUID, str | None]]]:
    replaced = {w.prescription.replaces_id for w in found if w.prescription.replaces_id}
    numbers = await repository.numbers({r for r in replaced if r is not None})
    newer = await repository.replacing({w.prescription.id for w in found})
    return numbers, newer


def _present(
    written: Written,
    numbers: dict[uuid.UUID, str | None],
    newer: dict[uuid.UUID, tuple[uuid.UUID, str | None]],
) -> dict[str, Any]:
    prescription = written.prescription
    replaces = prescription.replaces_id
    replaced_by = newer.get(prescription.id)
    return {
        "id": prescription.id,
        "number": prescription.prescription_number,
        "status": prescription.status,
        "issued_at": prescription.issued_at,
        "follow_up_date": prescription.follow_up_date,
        "instructions": prescription.instructions,
        "items": _items(written),
        "replaces": {"id": replaces, "number": numbers.get(replaces)} if replaces else None,
        "replaced_by": {"id": replaced_by[0], "number": replaced_by[1]}
        if replaced_by
        else None,
        "correction_reason": prescription.correction_reason,
    }


def _patient(written: Written, today: dt.date) -> dict[str, Any]:
    patient = written.patient
    return {
        "id": patient.id,
        "patient_number": patient.patient_number,
        "full_name": patient.full_name,
        "preferred_name": patient.preferred_name,
        "phone": patient.phone,
        "age": age_label(patient.date_of_birth, today),
        "gender": patient.gender,
        "status": patient.status,
        "allergy_count": written.allergy_count,
    }


async def for_consultation(
    session: AsyncSession, *, organization_id: uuid.UUID, consultation_id: uuid.UUID
) -> list[dict[str, Any]]:
    repository = PrescriptionRepository(session, organization_id)
    found = await repository.for_consultation(consultation_id)
    numbers, newer = await _links(repository, found)
    return [_present(written, numbers, newer) for written in found]


def _address(clinic: Organization) -> list[str]:
    address = clinic.address or {}
    place = ", ".join(
        part
        for part in (address.get("city"), address.get("state"), address.get("postal_code"))
        if part
    )
    return [line for line in (address.get("line1"), address.get("line2"), place) if line]


async def detail(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    may_correct: bool,
    prescription_id: uuid.UUID,
) -> dict[str, Any]:
    repository = PrescriptionRepository(session, organization_id)
    found = await repository.one(prescription_id)
    # A draft is still the doctor's own working, not something to print.
    if found is None or found.prescription.is_draft:
        raise PrescriptionNotFound
    numbers, newer = await _links(repository, [found])
    prescription, doctor = found.prescription, found.doctor
    visit = await session.get(Consultation, prescription.consultation_id)
    zone = clinic_zone(clinic)
    seen_at = visit.started_at if visit else prescription.issued_at or prescription.created_at
    return {
        **_present(found, numbers, newer),
        "patient": _patient(found, clinic_today(clinic)),
        "doctor": {
            "id": doctor.id,
            "display_name": doctor.display_name,
            "speciality": doctor.speciality,
            "qualifications": doctor.qualifications,
            "registration_number": doctor.registration_number,
        },
        "clinic": {
            "name": clinic.name,
            "address": _address(clinic),
            "phone": clinic.phone,
            "email": clinic.email,
        },
        "consultation_id": prescription.consultation_id,
        "visit_date": seen_at.astimezone(zone).date(),
        "can_correct": may_correct
        and prescription.status == rx.ISSUED
        and reach.narrowed
        and reach.doctor_id == prescription.doctor_id,
    }


async def listed(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    patient_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    found, total = await PrescriptionRepository(session, organization_id).issued(
        patient_id=patient_id, limit=limit, offset=offset
    )
    today = clinic_today(clinic)
    return {
        "items": [
            {
                "id": written.prescription.id,
                "number": written.prescription.prescription_number,
                "status": written.prescription.status,
                "issued_at": written.prescription.issued_at,
                "patient": _patient(written, today),
                "doctor": {
                    "id": written.doctor.id,
                    "display_name": written.doctor.display_name,
                    "speciality": written.doctor.speciality,
                    "room": written.doctor.room,
                    "status": written.doctor.status,
                },
                "medicines": [item.medicine_name for item in written.items],
            }
            for written in found
        ],
        "total": total,
    }


async def suggest(
    session: AsyncSession, *, organization_id: uuid.UUID, typed: str, limit: int
) -> list[dict[str, Any]]:
    found = await PrescriptionRepository(session, organization_id).suggestions(
        typed, limit=limit
    )
    return [
        {
            "name": s.name,
            "presentation": s.presentation,
            "source": s.source,
            "times_prescribed": s.times_prescribed,
        }
        for s in found
    ]
