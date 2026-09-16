from fastapi import APIRouter

from backend.api.v1 import health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
