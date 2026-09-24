from fastapi import APIRouter

from app.api.v1.endpoints import (
    appointments,
    audit,
    auth,
    billing,
    clinic,
    consultations,
    dashboard,
    doctors,
    documents,
    health,
    lab,
    notifications,
    patients,
    pay,
    prescriptions,
    queue,
    reports,
    search,
    vitals,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(clinic.router)
router.include_router(patients.router)
router.include_router(doctors.router)
router.include_router(appointments.router)
router.include_router(queue.router)
router.include_router(consultations.router)
router.include_router(prescriptions.router)
router.include_router(vitals.router)
router.include_router(lab.router)
router.include_router(documents.router)
router.include_router(billing.router)
router.include_router(pay.router)
router.include_router(dashboard.router)
router.include_router(reports.router)
router.include_router(notifications.router)
router.include_router(audit.router)
router.include_router(search.router)
