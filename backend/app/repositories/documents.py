"""Queries for the files on a patient's record."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select

from app.models import Consultation, LabOrder, PatientDocument, User
from app.repositories.base import TenantScopedRepository


@dataclass
class Filed:
    document: PatientDocument
    visit_started_at: dt.datetime | None
    lab_order_number: str | None
    lab_test_name: str | None
    uploaded_by: str | None


class DocumentRepository(TenantScopedRepository[PatientDocument]):
    model = PatientDocument

    def _joined(self) -> Select[Any]:
        return (
            select(
                PatientDocument,
                Consultation.started_at,
                LabOrder.order_number,
                LabOrder.test_name,
                User.first_name,
                User.last_name,
            )
            .outerjoin(Consultation, Consultation.id == PatientDocument.consultation_id)
            .outerjoin(LabOrder, LabOrder.id == PatientDocument.lab_order_id)
            .outerjoin(User, User.id == PatientDocument.uploaded_by_id)
            .where(PatientDocument.organization_id == self.organization_id)
        )

    async def _rows(self, statement: Select[Any]) -> list[Filed]:
        result = await self.session.execute(statement)
        return [
            Filed(
                document=row[0],
                visit_started_at=row[1],
                lab_order_number=row[2],
                lab_test_name=row[3],
                uploaded_by=f"{row[4]} {row[5]}".strip() if row[4] is not None else None,
            )
            for row in result.all()
        ]

    async def one(self, document_id: uuid.UUID, *, lock: bool = False) -> Filed | None:
        statement = (
            self._joined()
            .where(PatientDocument.id == document_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update(of=PatientDocument)
        found = await self._rows(statement)
        return found[0] if found else None

    def _conditions(
        self,
        *,
        patient_id: uuid.UUID,
        category: str | None,
        consultation_id: uuid.UUID | None,
        lab_order_id: uuid.UUID | None,
    ) -> list[ColumnElement[bool]]:
        conditions = [
            PatientDocument.organization_id == self.organization_id,
            PatientDocument.patient_id == patient_id,
        ]
        if category:
            conditions.append(PatientDocument.category == category)
        if consultation_id:
            conditions.append(PatientDocument.consultation_id == consultation_id)
        if lab_order_id:
            conditions.append(PatientDocument.lab_order_id == lab_order_id)
        return conditions

    async def listed(
        self,
        *,
        patient_id: uuid.UUID,
        category: str | None,
        consultation_id: uuid.UUID | None,
        lab_order_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Filed], int]:
        """Newest on the paper first, so an old report brought in today sits
        with its own year rather than at the top. Undated ones go by the day
        they were uploaded."""
        conditions = self._conditions(
            patient_id=patient_id,
            category=category,
            consultation_id=consultation_id,
            lab_order_id=lab_order_id,
        )
        when = func.coalesce(
            PatientDocument.dated, func.date(func.timezone("UTC", PatientDocument.created_at))
        )
        statement = (
            self._joined()
            .where(*conditions)
            .order_by(when.desc(), PatientDocument.created_at.desc(), PatientDocument.id.desc())
            .limit(limit)
            .offset(offset)
        )
        counted = select(func.count()).select_from(PatientDocument).where(*conditions)
        total = int((await self.session.execute(counted)).scalar_one())
        return await self._rows(statement), total

    async def counts(self, *, patient_id: uuid.UUID) -> dict[str, int]:
        result = await self.session.execute(
            select(PatientDocument.category, func.count())
            .where(PatientDocument.organization_id == self.organization_id)
            .where(PatientDocument.patient_id == patient_id)
            .group_by(PatientDocument.category)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def same_file(self, *, patient_id: uuid.UUID, sha256: str) -> PatientDocument | None:
        result = await self.session.execute(
            self.query()
            .where(PatientDocument.patient_id == patient_id)
            .where(PatientDocument.sha256 == sha256)
        )
        return result.scalar_one_or_none()
