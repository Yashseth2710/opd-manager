"""Files on a patient's record.

Anyone at the clinic who may upload can add a file to any patient: the desk
scans what the patient brings in, the doctor photographs a report in the
room. A file can be tied to the visit it came in for, or to a lab order whose
values were typed in from it, so the paper and the figures sit together.

Whoever put a file there can rename it, file it under something else, or
take it off, and so can the clinic admin. Nobody else, since the usual reason
to take a file off is that it went on the wrong patient, and that is a call
for the person who made the slip or the person who runs the clinic.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.exceptions import AppError, NotFound, ValidationFailed
from app.core.permissions import OWNER
from app.models import Consultation, LabOrder, Organization, PatientDocument, lab
from app.models.document import LAB_REPORT
from app.repositories.documents import DocumentRepository, Filed
from app.repositories.patients import PatientRepository
from app.schemas.document import MAX_BYTES, DocumentChange
from app.services import file_checks, plans
from app.services.doctors import clinic_today, clinic_zone
from app.services.patients import PatientArchived, PatientNotFound


class DocumentNotFound(NotFound):
    code = "DOC_NOT_FOUND"
    message = "That document could not be found."


class AlreadyUploaded(AppError):
    code = "DOC_ALREADY_UPLOADED"
    status = 409
    message = "That file is already on this patient's record."

    def __init__(self, message: str | None = None, *, existing: PatientDocument | None = None):
        super().__init__(message)
        # The one already there, so the page can offer to use it instead.
        self.candidates = (
            [{"id": str(existing.id), "title": existing.title}] if existing is not None else []
        )


class NotUploader(AppError):
    code = "DOC_NOT_UPLOADER"
    status = 403
    message = "Only whoever uploaded this file, or the clinic admin, can change it."


class TooLarge(AppError):
    code = "FILE_TOO_LARGE"
    status = 413
    message = "That file is larger than 4 MB."


class UnsupportedType(AppError):
    code = "FILE_UNSUPPORTED_TYPE"
    status = 415
    message = "Only PDFs and JPEG, PNG or WebP images can be added."


class UploadInterrupted(AppError):
    code = "FILE_UPLOAD_INTERRUPTED"
    status = 400
    message = "The upload stopped before the whole file arrived. Try again."


class UploadFailed(AppError):
    code = "FILE_UPLOAD_FAILED"
    status = 503
    message = "The file could not be stored just now. Try again in a moment."


class FileMissing(AppError):
    code = "FILE_MISSING"
    status = 404
    message = "The file for this document is missing from storage."


def may_change(document: PatientDocument, *, user_id: uuid.UUID, role: str) -> bool:
    return document.uploaded_by_id == user_id or role == OWNER


def _checked_date(dated: dt.date | None, today: dt.date) -> dt.date | None:
    if dated is None:
        return None
    if dated > today:
        raise ValidationFailed({"dated": "The date on it cannot be after today."})
    if dated.year < 1900:
        raise ValidationFailed({"dated": "That date is too far back."})
    return dated


def _kind_of(content: bytes, name: str) -> str:
    extension = file_checks.extension_of(name)
    if extension is not None and extension not in file_checks.ALLOWED_EXTENSIONS:
        raise UnsupportedType
    kind = file_checks.sniff(content[:2048])
    if kind == file_checks.HEIC:
        raise UnsupportedType(
            "That is an iPhone photo in HEIC, which browsers other than Safari "
            "cannot show. Share it as a JPEG, or take a screenshot of it, and add that."
        )
    if kind is None:
        raise UnsupportedType
    return kind


async def _visit(
    session: AsyncSession, organization_id: uuid.UUID, consultation_id: uuid.UUID
) -> Consultation | None:
    found = await session.get(Consultation, consultation_id)
    return found if found and found.organization_id == organization_id else None


async def _lab_order(
    session: AsyncSession, organization_id: uuid.UUID, order_id: uuid.UUID
) -> LabOrder | None:
    found = await session.get(LabOrder, order_id)
    return found if found and found.organization_id == organization_id else None


async def _order_for(
    session: AsyncSession,
    organization_id: uuid.UUID,
    patient_id: uuid.UUID,
    order_id: uuid.UUID,
) -> LabOrder:
    order = await _lab_order(session, organization_id, order_id)
    if order is None or order.patient_id != patient_id:
        raise ValidationFailed({"lab_order_id": "That lab order is not this patient's."})
    if order.status == lab.CANCELLED:
        raise ValidationFailed(
            {"lab_order_id": "That test was cancelled."},
            "That test was cancelled, so there is no report to add.",
        )
    return order


async def upload(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    actor_id: uuid.UUID,
    patient_id: uuid.UUID,
    content: bytes,
    name: str,
    declared_type: str | None,
    category: str,
    title: str | None,
    dated: dt.date | None,
    consultation_id: uuid.UUID | None,
    lab_order_id: uuid.UUID | None,
) -> uuid.UUID:
    patient = await PatientRepository(session, organization_id).get(patient_id)
    if patient is None:
        raise PatientNotFound
    if patient.is_archived:
        raise PatientArchived("This record is archived. Restore it before adding files.")

    if not content:
        raise ValidationFailed({"file": "That file is empty."}, "That file is empty.")
    if len(content) > MAX_BYTES:
        raise TooLarge
    original = file_checks.clean_name(name)
    kind = _kind_of(content, original)
    dated = _checked_date(dated, clinic_today(clinic))

    if lab_order_id is not None:
        order = await _order_for(session, organization_id, patient.id, lab_order_id)
        if category != LAB_REPORT:
            raise ValidationFailed({"category": "A lab's report is filed as a lab report."})
        if consultation_id is not None and consultation_id != order.consultation_id:
            raise ValidationFailed(
                {"consultation_id": "That test was ordered on another visit."}
            )
        consultation_id = order.consultation_id
    elif consultation_id is not None:
        visit = await _visit(session, organization_id, consultation_id)
        if visit is None or visit.patient_id != patient.id:
            raise ValidationFailed({"consultation_id": "That visit is not this patient's."})

    repository = DocumentRepository(session, organization_id)
    digest = hashlib.sha256(content).hexdigest()
    already = await repository.same_file(patient_id=patient.id, sha256=digest)
    if already is not None:
        raise AlreadyUploaded(
            f"That file is already on this record, as “{already.title}”.", existing=already
        )

    await plans.check(session, organization_id, "max_storage_mb", adding_bytes=len(content))

    pathname = (
        f"{organization_id}/{patient.id}/{uuid.uuid4().hex}.{file_checks.EXTENSION[kind]}"
    )
    try:
        url = await storage.put(pathname, content, kind)
    except storage.StorageUnavailable as exc:
        raise UploadFailed from exc

    document = PatientDocument(
        patient_id=patient.id,
        consultation_id=consultation_id,
        lab_order_id=lab_order_id,
        category=category,
        title=" ".join((title or "").split()) or file_checks.title_from(original),
        dated=dated,
        original_name=original,
        content_type=kind,
        declared_type=(declared_type or None) and declared_type[:100],
        size_bytes=len(content),
        sha256=digest,
        blob_url=url,
        uploaded_by_id=actor_id,
    )
    try:
        async with session.begin_nested():
            await repository.add(document)
    except IntegrityError as exc:
        # The same file from a second tab, a moment behind the first.
        await _forget(url)
        raise AlreadyUploaded from exc
    except BaseException:
        await _forget(url)
        raise
    return document.id


async def _forget(url: str) -> None:
    """Takes back a file whose row never made it. Failing here leaves a file
    no row points to, which is untidy and harmless."""
    with contextlib.suppress(storage.StorageUnavailable):
        await storage.delete(url)


async def _locked(
    session: AsyncSession, organization_id: uuid.UUID, document_id: uuid.UUID
) -> PatientDocument:
    found = await DocumentRepository(session, organization_id).one(document_id, lock=True)
    if found is None:
        raise DocumentNotFound
    return found.document


async def change(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    user_id: uuid.UUID,
    role: str,
    document_id: uuid.UUID,
    body: DocumentChange,
) -> None:
    document = await _locked(session, organization_id, document_id)
    if not may_change(document, user_id=user_id, role=role):
        raise NotUploader

    supplied = body.model_dump(exclude_unset=True)
    if "lab_order_id" in supplied:
        # A file already on the record, put with the test it is the report
        # for, or taken off it again.
        if body.lab_order_id is None:
            document.lab_order_id = None
        else:
            order = await _order_for(
                session, organization_id, document.patient_id, body.lab_order_id
            )
            document.lab_order_id = order.id
            document.consultation_id = order.consultation_id
            document.category = LAB_REPORT
    if "title" in supplied:
        if not body.title:
            raise ValidationFailed({"title": "Give it a name."})
        document.title = " ".join(body.title.split())
    if "category" in supplied:
        if body.category is None:
            raise ValidationFailed({"category": "Say what kind of file it is."})
        if document.lab_order_id is not None and body.category != LAB_REPORT:
            raise ValidationFailed(
                {"category": "This is the report for a lab test, so it stays a lab report."}
            )
        document.category = body.category
    if "dated" in supplied:
        document.dated = _checked_date(body.dated, clinic_today(clinic))
    await session.flush()


async def remove(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    document_id: uuid.UUID,
) -> None:
    """The row and the file both go. The file is deleted before the answer,
    so a file put on the wrong patient is gone from the store when the
    person who took it off is told it is."""
    document = await _locked(session, organization_id, document_id)
    if not may_change(document, user_id=user_id, role=role):
        raise NotUploader
    url = document.blob_url
    await session.delete(document)
    await session.flush()
    try:
        await storage.delete(url)
    except storage.StorageUnavailable as exc:
        raise UploadFailed(
            "The file could not be removed just now. Try again in a moment."
        ) from exc


async def content_of(
    session: AsyncSession, *, organization_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[PatientDocument, bytes]:
    found = await DocumentRepository(session, organization_id).one(document_id)
    if found is None:
        raise DocumentNotFound
    try:
        content = await storage.read(found.document.blob_url)
    except storage.Missing as exc:
        raise FileMissing from exc
    except storage.StorageUnavailable as exc:
        raise UploadFailed(
            "The file could not be fetched just now. Try again in a moment."
        ) from exc
    return found.document, content


def _present(
    found: Filed, *, clinic: Organization, user_id: uuid.UUID, role: str
) -> dict[str, Any]:
    document = found.document
    return {
        "id": document.id,
        "patient_id": document.patient_id,
        "category": document.category,
        "title": document.title,
        "dated": document.dated,
        "original_name": document.original_name,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "uploaded_at": document.created_at,
        "uploaded_by": found.uploaded_by,
        "consultation_id": document.consultation_id,
        "visit_date": (
            found.visit_started_at.astimezone(clinic_zone(clinic)).date()
            if found.visit_started_at
            else None
        ),
        "lab_order_id": document.lab_order_id,
        "lab_order_number": found.lab_order_number,
        "lab_test_name": found.lab_test_name,
        "can_change": may_change(document, user_id=user_id, role=role),
    }


async def detail(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    user_id: uuid.UUID,
    role: str,
    may_upload: bool,
    document_id: uuid.UUID,
) -> dict[str, Any]:
    found = await DocumentRepository(session, organization_id).one(document_id)
    if found is None:
        raise DocumentNotFound
    presented = _present(found, clinic=clinic, user_id=user_id, role=role)
    presented["can_change"] = presented["can_change"] and may_upload
    return presented


async def listed(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    user_id: uuid.UUID,
    role: str,
    may_upload: bool,
    patient_id: uuid.UUID,
    category: str | None,
    consultation_id: uuid.UUID | None,
    lab_order_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    if await PatientRepository(session, organization_id).get(patient_id) is None:
        raise PatientNotFound
    repository = DocumentRepository(session, organization_id)
    found, total = await repository.listed(
        patient_id=patient_id,
        category=category,
        consultation_id=consultation_id,
        lab_order_id=lab_order_id,
        limit=limit,
        offset=offset,
    )
    items = []
    for each in found:
        presented = _present(each, clinic=clinic, user_id=user_id, role=role)
        presented["can_change"] = presented["can_change"] and may_upload
        items.append(presented)
    return {
        "items": items,
        "total": total,
        "counts": await repository.counts(patient_id=patient_id),
    }
