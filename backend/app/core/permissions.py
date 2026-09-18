"""The permission catalogue and the roles a new clinic starts with.

Permission strings are shaped `resource:action` and are the only vocabulary
route dependencies check against. Where the matrix says a role sees only its
own records, the permission is still granted here and the narrowing happens
in the query; a permission string cannot express "own".
"""

from __future__ import annotations

from typing import Final

CATALOGUE: Final[dict[str, str]] = {
    "patient:create": "Register a patient",
    "patient:read": "View patient records",
    "patient:update": "Edit patient details",
    "patient:archive": "Archive and restore patients",
    "appointment:create": "Book appointments",
    "appointment:read": "View appointments",
    "appointment:update": "Reschedule appointments",
    "appointment:cancel": "Cancel appointments",
    "queue:checkin": "Check patients into the queue",
    "queue:manage": "Call, move and close queue entries",
    "consultation:create": "Start a consultation",
    "consultation:read": "Read consultation notes",
    "consultation:update": "Edit consultation notes",
    "prescription:create": "Write prescriptions",
    "prescription:read": "View prescriptions",
    "lab:create": "Order lab tests",
    "lab:update": "Record lab results",
    "document:upload": "Upload documents",
    "document:read": "View documents",
    "billing:create": "Raise invoices",
    "billing:read": "View invoices",
    "billing:update": "Edit and void invoices",
    "payment:record": "Record payments",
    "reports:read": "View reports",
    "doctor:read": "View doctors and their hours",
    "doctor:manage": "Add and edit doctors",
    "staff:manage": "Invite and manage staff",
    "settings:manage": "Change clinic settings",
    "subscription:manage": "Manage the subscription",
    "audit:read": "Read the audit log",
    "platform:manage": "Administer the platform",
}

OWNER: Final[str] = "clinic-admin"

# The one role whose view of appointments is narrowed to its own list. The
# matrix marks it "own", which a permission string cannot say.
DOCTOR: Final[str] = "doctor"

# Clinical documentation is deliberately absent from the admin role. An
# administrator can read a consultation but never author one, because the
# clinician who signs a note is the one accountable for it.
_CLINIC_ADMIN = [
    "patient:create",
    "patient:read",
    "patient:update",
    "patient:archive",
    "appointment:create",
    "appointment:read",
    "appointment:update",
    "appointment:cancel",
    "queue:checkin",
    "queue:manage",
    "consultation:read",
    "prescription:read",
    "lab:update",
    "document:upload",
    "document:read",
    "billing:create",
    "billing:read",
    "billing:update",
    "payment:record",
    "reports:read",
    "doctor:read",
    "doctor:manage",
    "staff:manage",
    "settings:manage",
    "subscription:manage",
    "audit:read",
]

_DOCTOR = [
    "patient:create",
    "patient:read",
    "patient:update",
    "appointment:create",
    "appointment:read",
    "appointment:update",
    "appointment:cancel",
    "queue:manage",
    "consultation:create",
    "consultation:read",
    "consultation:update",
    "prescription:create",
    "prescription:read",
    "lab:create",
    "lab:update",
    "document:upload",
    "document:read",
    "reports:read",
    "doctor:read",
]

_RECEPTIONIST = [
    "patient:create",
    "patient:read",
    "patient:update",
    "appointment:create",
    "appointment:read",
    "appointment:update",
    "appointment:cancel",
    "queue:checkin",
    "queue:manage",
    "prescription:read",
    "document:upload",
    "document:read",
    "billing:create",
    "billing:read",
    "billing:update",
    "payment:record",
    "doctor:read",
]

# Intentionally thin. The matrix marks most of this role as the clinic
# admin's decision, so it starts at read-only and is widened deliberately.
_STAFF = [
    "patient:read",
    "appointment:read",
    "document:read",
    "doctor:read",
]

DEFAULT_ROLES: Final[tuple[tuple[str, str, str, list[str]], ...]] = (
    (
        OWNER,
        "Clinic admin",
        "Runs the clinic: staff, settings, billing and reports.",
        _CLINIC_ADMIN,
    ),
    (DOCTOR, "Doctor", "Sees patients, writes notes and prescriptions.", _DOCTOR),
    (
        "receptionist",
        "Receptionist",
        "Registers patients, books appointments and takes payment.",
        _RECEPTIONIST,
    ),
    ("staff", "Staff", "General clinic staff. Starts read-only.", _STAFF),
)


def unknown_codes() -> set[str]:
    """Guards against a role naming a permission the catalogue does not hold."""
    granted = {code for _, _, _, codes in DEFAULT_ROLES for code in codes}
    return granted - set(CATALOGUE)
