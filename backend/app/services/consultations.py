"""Consultation notes: opened in the room, written as a draft, finished once.

Notes belong to the doctor who saw the patient. Only that doctor writes
them, and only that doctor and the clinic admin read them; a colleague does
not, which is the line the permission matrix draws.

A save names the version of the note it was written against. Two tabs open
on the same draft would otherwise take turns silently undoing each other,
and the one that loses is ten minutes of somebody's typing.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound, PermissionDenied, ValidationFailed
from app.models import Appointment, Consultation, Organization
from app.models import consultation as notes
from app.models import queue as line
from app.repositories.consultations import ConsultationRepository, Written
from app.repositories.queue import QueueRepository
from app.schemas.consultation import ConsultationWrite
from app.services import prescriptions, queue
from app.services.appointments import Reach
from app.services.doctors import clinic_today, clinic_zone
from app.services.patients import age_label

# The furthest ahead a follow-up is written. Anything later is a new
# problem by the time it comes round, not a follow-up.
FOLLOW_UP_LIMIT_DAYS = 365


class ConsultationNotFound(NotFound):
    code = "CONSULT_NOT_FOUND"
    message = "Those notes could not be found."


class NotOwner(AppError):
    code = "CONSULT_NOT_OWNER"
    status = 403
    message = "Only the doctor who saw this patient can do that."


class AlreadyCompleted(AppError):
    code = "CONSULT_ALREADY_COMPLETED"
    status = 409
    message = "These notes are finished. Add an addendum instead."


class StillDraft(AppError):
    code = "CONSULT_STILL_DRAFT"
    status = 409
    message = "These notes are still a draft. Change them directly instead."


class EditedElsewhere(AppError):
    code = "CONSULT_EDITED_ELSEWHERE"
    status = 409
    message = "These notes were changed in another window. Reload them before carrying on."


class NotInRoom(AppError):
    code = "CONSULT_NOT_IN_ROOM"
    status = 409
    message = "Bring the patient in before starting their notes."


class Unlinked(PermissionDenied):
    message = (
        "Your account is not linked to a doctor profile yet. "
        "Ask the clinic admin to link it before writing notes."
    )


_NOT_IN_ROOM_BECAUSE = {
    line.WAITING: "They are still waiting. Bring them in before starting their notes.",
    line.CALLED: "They have been called and not come in yet.",
    line.SKIPPED: "They missed their call. Recall them and bring them in first.",
    line.NO_SHOW: "They were marked as gone, so there is no visit to write up.",
}


def _is_author(reach: Reach, doctor_id: uuid.UUID) -> bool:
    return reach.narrowed and reach.doctor_id == doctor_id


def _visit_date(consultation: Consultation, clinic: Organization) -> dt.date:
    return consultation.started_at.astimezone(clinic_zone(clinic)).date()


def _blank(value: str | None) -> str | None:
    return value if value else None


# --- Opening ---------------------------------------------------------------


async def open_for(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> tuple[Consultation, bool]:
    """The notes for a patient in the room, made the first time they are
    asked for. Says whether they were made just now."""
    if not reach.narrowed:
        raise PermissionDenied("Notes are written by the doctor who sees the patient.")
    if reach.doctor_id is None:
        raise Unlinked

    queued = QueueRepository(session, organization_id)
    # Locked, so two tabs opening the notes at once take turns and the
    # second finds what the first made.
    placed = await queued.one(entry_id, lock=True)
    if placed is None or not reach.covers(placed.doctor.id):
        raise queue.QueueEntryNotFound

    written = ConsultationRepository(session, organization_id)
    existing = await written.for_queue_entry(entry_id)
    if existing is not None:
        return existing, False

    entry = placed.entry
    if entry.status not in (line.IN_CONSULTATION, line.COMPLETED):
        raise NotInRoom(_NOT_IN_ROOM_BECAUSE.get(entry.status))

    consultation = Consultation(
        queue_entry_id=entry.id,
        appointment_id=entry.appointment_id,
        patient_id=entry.patient_id,
        doctor_id=entry.doctor_id,
        status=notes.DRAFT,
        version=1,
        started_at=entry.started_at or dt.datetime.now(dt.UTC),
        written_by_id=actor_id,
    )
    # A walk-in's reason is the obvious start of the complaint, and the
    # booked reason is the same for an appointment.
    reason = entry.reason or (placed.appointment.reason if placed.appointment else None)
    if reason:
        consultation.chief_complaint = reason[:500]
    await written.add(consultation)
    return consultation, True


# --- Writing ---------------------------------------------------------------


async def _for_writing(
    session: AsyncSession, organization_id: uuid.UUID, reach: Reach, consultation_id: uuid.UUID
) -> Written:
    found = await ConsultationRepository(session, organization_id).one(
        consultation_id, lock=True
    )
    if found is None or reach.unlinked:
        raise ConsultationNotFound
    if not _is_author(reach, found.doctor.id):
        raise NotOwner(
            f"These notes are {found.doctor.display_name}'s. Only they can change them."
        )
    return found


def _check_version(consultation: Consultation, version: int) -> None:
    if consultation.version != version:
        raise EditedElsewhere


def _diagnoses(body: ConsultationWrite) -> list[tuple[str, bool]]:
    given = body.diagnoses or []
    seen: set[str] = set()
    for index, diagnosis in enumerate(given):
        key = " ".join(diagnosis.label.lower().split())
        if key in seen:
            raise ValidationFailed(
                {f"diagnoses.{index}.label": "That diagnosis is already listed."},
                "That diagnosis is already listed.",
            )
        seen.add(key)

    primaries = [d for d in given if d.is_primary]
    if len(primaries) > 1:
        raise ValidationFailed(
            {"diagnoses": "Only one diagnosis can be the main one."},
            "Only one diagnosis can be the main one.",
        )
    # Somebody writing a single diagnosis should not have to also say it is
    # the main one.
    lead = primaries[0] if primaries else (given[0] if given else None)
    return [(d.label, d is lead) for d in given]


def _check_follow_up(value: dt.date, visit: dt.date) -> None:
    if value <= visit:
        raise ValidationFailed(
            {"follow_up_date": "Pick a day after the visit."}, "Pick a day after the visit."
        )
    if value > visit + dt.timedelta(days=FOLLOW_UP_LIMIT_DAYS):
        raise ValidationFailed(
            {"follow_up_date": "Keep a follow-up within a year of the visit."},
            "Keep a follow-up within a year of the visit.",
        )


async def save(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    consultation_id: uuid.UUID,
    body: ConsultationWrite,
) -> None:
    found = await _for_writing(session, organization_id, reach, consultation_id)
    consultation = found.consultation
    if not consultation.is_draft:
        raise AlreadyCompleted
    _check_version(consultation, body.version)

    sent = body.model_fields_set
    for name in ("chief_complaint", "history", "examination", "advice"):
        if name in sent:
            setattr(consultation, name, _blank(getattr(body, name)))
    if "follow_up_date" in sent:
        if body.follow_up_date is not None:
            _check_follow_up(body.follow_up_date, _visit_date(consultation, clinic))
        consultation.follow_up_date = body.follow_up_date
    if "diagnoses" in sent:
        await ConsultationRepository(session, organization_id).replace_diagnoses(
            consultation.id, _diagnoses(body)
        )
    if "medicines" in sent or "prescription_instructions" in sent:
        await prescriptions.write_draft(
            session,
            organization_id=organization_id,
            consultation=consultation,
            lines=body.medicines,
            instructions=body.prescription_instructions,
            sent_lines="medicines" in sent,
            sent_instructions="prescription_instructions" in sent,
        )

    consultation.version += 1
    await session.flush()


async def finish(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    consultation_id: uuid.UUID,
    version: int,
) -> None:
    """Locks the notes and issues the prescription written with them. If the
    patient is still shown in the room, they are finished there too, so the
    doctor does not have to do it twice."""
    found = await _for_writing(session, organization_id, reach, consultation_id)
    consultation = found.consultation
    if not consultation.is_draft:
        raise AlreadyCompleted
    _check_version(consultation, version)

    # Checked before anything is locked, so a line without a dose leaves the
    # visit open to be put right.
    prescription = await prescriptions.ready_to_issue(
        session, organization_id=organization_id, consultation=consultation
    )
    written = any(
        (
            consultation.chief_complaint,
            consultation.history,
            consultation.examination,
            consultation.advice,
            found.diagnoses,
            prescription,
        )
    )
    if not written:
        raise ValidationFailed(
            {"notes": "Write the complaint or a diagnosis before finishing."},
            "Write the complaint or a diagnosis before finishing.",
        )

    consultation.status = notes.COMPLETED
    consultation.completed_at = dt.datetime.now(dt.UTC)
    consultation.version += 1
    await session.flush()
    if prescription is not None:
        await prescriptions.issue(
            session,
            organization_id=organization_id,
            prescription=prescription,
            follow_up_date=consultation.follow_up_date,
            actor_id=actor_id,
        )

    if consultation.queue_entry_id is None:
        return
    placed = await QueueRepository(session, organization_id).one(consultation.queue_entry_id)
    if placed is not None and placed.entry.status == line.IN_CONSULTATION:
        await queue.complete(
            session,
            organization_id=organization_id,
            reach=reach,
            actor_id=actor_id,
            entry_id=consultation.queue_entry_id,
        )


async def add_addendum(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    reach: Reach,
    actor_id: uuid.UUID,
    consultation_id: uuid.UUID,
    body: str,
) -> None:
    found = await _for_writing(session, organization_id, reach, consultation_id)
    if found.consultation.is_draft:
        raise StillDraft
    await ConsultationRepository(session, organization_id).add_addendum(
        found.consultation.id, body, actor_id
    )


# --- Reading ---------------------------------------------------------------


def _summary(found: Written, clinic: Organization, today: dt.date) -> dict[str, Any]:
    consultation, patient, doctor = found.consultation, found.patient, found.doctor
    primary = next((d for d in found.diagnoses if d.is_primary), None)
    return {
        "id": consultation.id,
        "status": consultation.status,
        "patient": {
            "id": patient.id,
            "patient_number": patient.patient_number,
            "full_name": patient.full_name,
            "preferred_name": patient.preferred_name,
            "phone": patient.phone,
            "age": age_label(patient.date_of_birth, today),
            "gender": patient.gender,
            "status": patient.status,
            "allergy_count": found.allergy_count,
        },
        "doctor": {
            "id": doctor.id,
            "display_name": doctor.display_name,
            "speciality": doctor.speciality,
            "room": doctor.room,
            "status": doctor.status,
        },
        "visit_date": _visit_date(consultation, clinic),
        "started_at": consultation.started_at,
        "completed_at": consultation.completed_at,
        "token": found.token,
        "chief_complaint": consultation.chief_complaint,
        "primary_diagnosis": primary.label if primary else None,
        "diagnosis_count": len(found.diagnoses),
        "follow_up_date": consultation.follow_up_date,
        "addendum_count": found.addendum_count,
    }


async def listed(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    doctor_id: uuid.UUID | None,
    patient_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """A doctor's list is always their own, whatever they ask for."""
    if reach.unlinked:
        return {"items": [], "total": 0}
    if reach.narrowed:
        doctor_id = reach.doctor_id
    found, total = await ConsultationRepository(session, organization_id).listed(
        doctor_id=doctor_id, patient_id=patient_id, status=status, limit=limit, offset=offset
    )
    today = clinic_today(clinic)
    return {"items": [_summary(each, clinic, today) for each in found], "total": total}


async def detail(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    reach: Reach,
    can_write: bool,
    consultation_id: uuid.UUID,
) -> dict[str, Any]:
    repository = ConsultationRepository(session, organization_id)
    found = await repository.one(consultation_id)
    if found is None or reach.unlinked:
        raise ConsultationNotFound
    if not reach.covers(found.doctor.id):
        # Inside the clinic the visit is no secret, only what was written.
        raise NotOwner(
            f"These notes are {found.doctor.display_name}'s. "
            "Only they and the clinic admin can read them."
        )

    consultation = found.consultation
    appointment = (
        await session.get(Appointment, consultation.appointment_id)
        if consultation.appointment_id
        else None
    )
    zone = clinic_zone(clinic)
    author = can_write and _is_author(reach, found.doctor.id)
    return {
        **_summary(found, clinic, clinic_today(clinic)),
        "version": consultation.version,
        "queue_entry_id": consultation.queue_entry_id,
        "appointment": {
            "id": appointment.id,
            "start_time": appointment.scheduled_start.astimezone(zone).time(),
            "end_time": appointment.scheduled_end.astimezone(zone).time(),
            "appointment_type": appointment.appointment_type,
            "reason": appointment.reason,
            "status": appointment.status,
        }
        if appointment is not None and appointment.organization_id == organization_id
        else None,
        "history": consultation.history,
        "examination": consultation.examination,
        "advice": consultation.advice,
        "diagnoses": [{"label": d.label, "is_primary": d.is_primary} for d in found.diagnoses],
        "addenda": [
            {
                "id": added.addendum.id,
                "body": added.addendum.body,
                "written_by": added.written_by,
                "created_at": added.addendum.created_at,
            }
            for added in await repository.addenda(consultation.id)
        ],
        "prescriptions": await prescriptions.for_consultation(
            session, organization_id=organization_id, consultation_id=consultation.id
        ),
        "updated_at": consultation.updated_at,
        "can_edit": author and consultation.is_draft,
        "can_add_addendum": author and not consultation.is_draft,
    }
