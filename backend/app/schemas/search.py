"""What the search box finds, one short list per kind of record."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Kind = Literal["patients", "appointments", "bills", "doctors", "staff"]


class FoundPatient(BaseModel):
    id: uuid.UUID
    patient_number: str
    full_name: str
    phone: str | None
    age: str | None
    gender: str | None
    archived: bool


class FoundAppointment(BaseModel):
    id: uuid.UUID
    patient_name: str
    patient_number: str
    doctor_name: str
    starts_at: dt.datetime
    status: str


class FoundBill(BaseModel):
    id: uuid.UUID
    invoice_number: str | None
    status: str
    total: Decimal
    balance: Decimal
    patient_name: str
    placed_at: dt.datetime


class FoundDoctor(BaseModel):
    id: uuid.UUID
    display_name: str
    speciality: str | None
    active: bool


class FoundColleague(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    role: str | None
    active: bool


class Found(BaseModel):
    query: str
    # The kinds this caller's role lets them search, whether or not anything
    # matched, so "nothing found" can say where it looked.
    searched: list[Kind]
    patients: list[FoundPatient]
    appointments: list[FoundAppointment]
    bills: list[FoundBill]
    doctors: list[FoundDoctor]
    staff: list[FoundColleague]
