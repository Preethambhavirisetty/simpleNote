from fastapi import APIRouter

from app.schema.responses import HealthData

router = APIRouter(tags=['base'])


@router.get('/health', response_model=HealthData, summary="Check backend health")
def health_check():
    """Return a lightweight backend liveness response."""
    return {"STATUS": "OK"}
