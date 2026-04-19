"""API router — combines all route modules under /api prefix."""

from fastapi import APIRouter, Depends

from apis.deps import require_api_key
from apis.routes.ingest import router as ingest_router
from apis.routes.intent import router as intent_router
from apis.routes.retrieve import router as retrieve_router
from apis.routes.chat import router as chat_router

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)

router.include_router(ingest_router)
router.include_router(intent_router)
router.include_router(retrieve_router)
router.include_router(chat_router)
