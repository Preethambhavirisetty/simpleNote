from fastapi import APIRouter

from app.core.feature_flags import get_all_resolved

router = APIRouter(tags=["feature-flags"])


@router.get("/feature-flags", response_model=dict[str, bool], summary="List resolved feature flags")
def list_feature_flags():
    """Public endpoint — returns the resolved flat map of all feature flags."""
    return get_all_resolved()
