"""One box that finds a patient, a booking, a bill, a doctor or a colleague.

Each kind is searched only when the caller's role could open what it finds,
so the box never lists a record whose page would refuse them. Every query
goes through a repository scoped to the caller's clinic, and a doctor's
bookings are narrowed to their own list exactly as the appointments page is.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization
from app.models.doctor import ACTIVE as DOCTOR_ACTIVE
from app.models.patient import ARCHIVED
from app.repositories import patients as patient_rows
from app.repositories.appointments import AppointmentRepository
from app.repositories.billing import InvoiceRepository
from app.repositories.doctors import DoctorRepository
from app.repositories.staff import StaffRepository
from app.schemas.search import (
    FoundAppointment,
    FoundBill,
    FoundColleague,
    FoundDoctor,
    FoundPatient,
    Kind,
)
from app.services import appointments
from app.services.doctors import clinic_today, day_bounds
from app.services.patients import age_label

# One letter matches half the register, which is a list, not a search.
SHORTEST = 2

# Enough to find the one somebody meant, few enough to read at a glance. The
# page behind each kind has the rest.
EACH = 5

_NEEDS: dict[Kind, str] = {
    "patients": "patient:read",
    "appointments": "appointment:read",
    "bills": "billing:read",
    "doctors": "doctor:read",
    "staff": "staff:manage",
}


@dataclass
class Results:
    query: str
    searched: list[Kind]
    patients: list[FoundPatient] = field(default_factory=list)
    appointments: list[FoundAppointment] = field(default_factory=list)
    bills: list[FoundBill] = field(default_factory=list)
    doctors: list[FoundDoctor] = field(default_factory=list)
    staff: list[FoundColleague] = field(default_factory=list)


async def find(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    clinic: Organization,
    user_id: uuid.UUID,
    role: str,
    permissions: frozenset[str],
    typed: str,
) -> Results:
    term = " ".join(typed.split())
    searched: list[Kind] = [kind for kind, needs in _NEEDS.items() if needs in permissions]
    found = Results(query=term, searched=searched)
    if len(term) < SHORTEST:
        return found

    if "patients" in searched:
        matched = await patient_rows.PatientRepository(session, organization_id).closest(
            term, limit=EACH
        )
        found.patients = [
            FoundPatient(
                id=patient.id,
                patient_number=patient.patient_number,
                full_name=patient.full_name,
                phone=patient.phone,
                age=age_label(patient.date_of_birth),
                gender=patient.gender,
                archived=patient.status == ARCHIVED,
            )
            for patient in matched
        ]

    if "appointments" in searched:
        reach = await appointments.reach_of(
            session, organization_id=organization_id, user_id=user_id, role=role
        )
        # A doctor's account with no profile linked has no list to search.
        if not reach.unlinked:
            since, _ = day_bounds(clinic, clinic_today(clinic))
            booked = await AppointmentRepository(session, organization_id).coming_up(
                patient_rows.matching(term),
                since,
                doctor_id=reach.doctor_id if reach.narrowed else None,
                limit=EACH,
            )
            found.appointments = [
                FoundAppointment(
                    id=row.appointment.id,
                    patient_name=row.patient.full_name,
                    patient_number=row.patient.patient_number,
                    doctor_name=row.doctor.display_name,
                    starts_at=row.appointment.scheduled_start,
                    status=row.appointment.status,
                )
                for row in booked
            ]

    if "bills" in searched:
        billed = await InvoiceRepository(session, organization_id).latest_matching(
            term, limit=EACH
        )
        found.bills = [
            FoundBill(
                id=invoice.id,
                invoice_number=invoice.invoice_number,
                status=invoice.status,
                total=invoice.total,
                balance=invoice.balance,
                patient_name=patient.full_name,
                placed_at=invoice.issued_at or invoice.created_at,
            )
            for invoice, patient in billed
        ]

    if "doctors" in searched:
        doctors = await DoctorRepository(session, organization_id).closest(term, limit=EACH)
        found.doctors = [
            FoundDoctor(
                id=doctor.id,
                display_name=doctor.display_name,
                speciality=doctor.speciality,
                active=doctor.status == DOCTOR_ACTIVE,
            )
            for doctor in doctors
        ]

    if "staff" in searched:
        people = await StaffRepository(session, organization_id).named(term, limit=EACH)
        found.staff = [
            FoundColleague(
                id=user.id,
                full_name=f"{user.first_name} {user.last_name}".strip(),
                email=user.email,
                role=held.name if held else None,
                active=user.status == "active",
            )
            for user, held in people
        ]

    return found
