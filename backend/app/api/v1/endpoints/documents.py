"""Files on a patient's record, and the files themselves."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.api.deps import Caller, DbSession, Trail, current_tenant, requires
from app.core import rate_limit
from app.core.exceptions import NotFound
from app.models import Organization
from app.schemas.document import (
    MAX_BYTES,
    Category,
    DocumentChange,
    DocumentOut,
    DocumentPage,
    Removed,
)
from app.services import documents as service
from app.services import events, file_checks

router = APIRouter(tags=["documents"])


async def _clinic(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    clinic = await session.get(Organization, organization_id)
    if clinic is None:
        raise NotFound
    return clinic


async def _answer(
    session: AsyncSession, organization_id: uuid.UUID, caller: Caller, document_id: uuid.UUID
) -> DocumentOut:
    found = await service.detail(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        user_id=caller.user_id,
        role=caller.role,
        may_upload=caller.may("document:upload"),
        document_id=document_id,
    )
    return DocumentOut.model_validate(found)


async def _body(request: Request) -> bytes:
    """The file, read no further than the limit. A sender that says it is
    sending more than that is turned away before anything is read."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise service.TooLarge
    received = bytearray()
    try:
        async for chunk in request.stream():
            received += chunk
            if len(received) > MAX_BYTES:
                raise service.TooLarge
    except ClientDisconnect as exc:
        # Stopped from the page, or the connection went. Nobody is left to
        # read the answer, but it should not read as a fault in the log.
        raise service.UploadInterrupted from exc
    return bytes(received)


@router.get("/patients/{patient_id}/documents")
async def list_documents(
    session: DbSession,
    patient_id: uuid.UUID,
    category: Category | None = Query(default=None),
    consultation_id: uuid.UUID | None = Query(default=None),
    lab_order_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    caller: Caller = Depends(requires("document:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DocumentPage:
    found = await service.listed(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        user_id=caller.user_id,
        role=caller.role,
        may_upload=caller.may("document:upload"),
        patient_id=patient_id,
        category=category,
        consultation_id=consultation_id,
        lab_order_id=lab_order_id,
        limit=limit,
        offset=offset,
    )
    return DocumentPage.model_validate(found)


@router.post("/patients/{patient_id}/documents", status_code=201)
async def upload_document(
    session: DbSession,
    request: Request,
    patient_id: uuid.UUID,
    trail: Trail,
    name: str = Query(min_length=1, max_length=255),
    category: Category = Query(),
    title: str | None = Query(default=None, max_length=120),
    dated: dt.date | None = Query(default=None),
    consultation_id: uuid.UUID | None = Query(default=None),
    lab_order_id: uuid.UUID | None = Query(default=None),
    caller: Caller = Depends(requires("document:upload")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DocumentOut:
    """The file is the whole request body, sent as it is. What it is and who
    it belongs to travel in the query, so nothing has to be unpacked from a
    form before the size can be checked."""
    await rate_limit.check("upload", str(caller.user_id), rate_limit.UPLOAD_PER_USER)
    content = await _body(request)
    document_id = await service.upload(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        actor_id=caller.user_id,
        patient_id=patient_id,
        content=content,
        name=name,
        declared_type=request.headers.get("content-type"),
        category=category,
        title=title,
        dated=dated,
        consultation_id=consultation_id,
        lab_order_id=lab_order_id,
    )
    found = await _answer(session, organization_id, caller, document_id)
    await trail(
        "document.uploaded",
        "document",
        found.patient_id,
        await events.patient_named(session, organization_id, found.patient_id),
        {"title": found.title, "category": found.category},
    )
    return found


@router.get("/documents/{document_id}")
async def read_document(
    session: DbSession,
    document_id: uuid.UUID,
    caller: Caller = Depends(requires("document:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DocumentOut:
    return await _answer(session, organization_id, caller, document_id)


_UNSAFE_IN_HEADER = re.compile(r"[^A-Za-z0-9 ._()-]")


def _disposition(kind: str, title: str, content_type: str) -> str:
    """The title as the file's name, with the right extension whatever it was
    sent with. A plain ASCII copy for old clients, the real one beside it."""
    name = f"{title}.{file_checks.EXTENSION[content_type]}"
    plain = _UNSAFE_IN_HEADER.sub("_", name)
    return f"{kind}; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"


@router.get("/documents/{document_id}/file")
async def document_file(
    session: DbSession,
    document_id: uuid.UUID,
    download: bool = Query(default=False),
    caller: Caller = Depends(requires("document:read")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Response:
    """The file, fetched from the store for someone allowed to see it. The
    store's own address never leaves the server."""
    document, content = await service.content_of(
        session, organization_id=organization_id, document_id=document_id
    )
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            "Content-Disposition": _disposition(
                "attachment" if download else "inline", document.title, document.content_type
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.patch("/documents/{document_id}")
async def change_document(
    session: DbSession,
    document_id: uuid.UUID,
    body: DocumentChange,
    trail: Trail,
    caller: Caller = Depends(requires("document:upload")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> DocumentOut:
    before = await _answer(session, organization_id, caller, document_id)
    await service.change(
        session,
        organization_id=organization_id,
        clinic=await _clinic(session, organization_id),
        user_id=caller.user_id,
        role=caller.role,
        document_id=document_id,
        body=body,
    )
    after = await _answer(session, organization_id, caller, document_id)
    shown = ("title", "category", "dated")
    moved = events.difference(events.snapshot(before, shown), events.snapshot(after, shown))
    if moved:
        await trail(
            "document.changed",
            "document",
            after.patient_id,
            await events.patient_named(session, organization_id, after.patient_id),
            moved,
        )
    return after


@router.delete("/documents/{document_id}")
async def remove_document(
    session: DbSession,
    document_id: uuid.UUID,
    trail: Trail,
    caller: Caller = Depends(requires("document:upload")),
    organization_id: uuid.UUID = Depends(current_tenant),
) -> Removed:
    removed = await _answer(session, organization_id, caller, document_id)
    await service.remove(
        session,
        organization_id=organization_id,
        user_id=caller.user_id,
        role=caller.role,
        document_id=document_id,
    )
    await trail(
        "document.removed",
        "document",
        removed.patient_id,
        await events.patient_named(session, organization_id, removed.patient_id),
        {"title": removed.title},
    )
    return Removed()
