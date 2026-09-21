"""Request and response shapes for the files on a patient's record."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "lab_report", "scan", "prescription", "referral", "discharge", "insurance", "other"
]
ContentType = Literal["application/pdf", "image/jpeg", "image/png", "image/webp"]

# Vercel refuses a request to a function once its body passes 4.5 MB, before
# the API sees it. A little under that leaves room for the headers. The web
# app shrinks a large photo to fit before sending it.
MAX_BYTES = 4 * 1024 * 1024


class DocumentChange(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    category: Category | None = None
    dated: dt.date | None = None
    lab_order_id: uuid.UUID | None = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    category: Category
    title: str
    dated: dt.date | None
    original_name: str
    content_type: ContentType
    size_bytes: int
    uploaded_at: dt.datetime
    uploaded_by: str | None
    consultation_id: uuid.UUID | None
    visit_date: dt.date | None
    lab_order_id: uuid.UUID | None
    lab_order_number: str | None
    lab_test_name: str | None
    can_change: bool


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    total: int
    # Every file on the record by category, whatever the list was narrowed to.
    counts: dict[str, int]


class Removed(BaseModel):
    removed: Literal[True] = True
