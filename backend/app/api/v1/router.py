from fastapi import APIRouter

from app.api.v1.endpoints import auth, clinic, doctors, health, patients

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(clinic.router)
router.include_router(patients.router)
router.include_router(doctors.router)
