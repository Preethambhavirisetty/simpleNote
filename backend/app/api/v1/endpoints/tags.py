from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.schema.responses import ApiResponse, TagData

from app.db.postgres.models.tag import Tag
from app.db.postgres.session import get_postgres_session
from app.deps.auth import get_current_user
from app.exceptions.handlers import success_response
from app.schema.tag import TagCreate, TagUpdate
from app.services.tags import TagService

router = APIRouter(prefix="/tags", tags=["tags"])


def get_tag_service():
    return TagService()


def _tag_dict(tag: Tag) -> dict:
    return {
        "id": str(tag.id),
        "user_id": str(tag.user_id),
        "name": tag.name,
        "created_at": tag.created_at.isoformat(),
    }


@router.get("/", response_model=ApiResponse[list[TagData]], summary="List tags")
def list_tags(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    """List tags owned by the authenticated user."""
    tags = service.list(db, current_user.id)
    return success_response([_tag_dict(t) for t in tags], "Tags retrieved")


@router.post("/", response_model=ApiResponse[TagData], summary="Create a tag")
def create_tag(
    payload: TagCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    """Create a tag for the authenticated user."""
    tag = service.create(db, current_user.id, payload)
    return success_response(_tag_dict(tag), "Tag created")


# -- Internal service routes (Agent -> Backend) ------------------------------

def _internal_user_id(x_internal_key: str, x_user_id: str) -> UUID:
    from app.deps.internal import verify_internal_key

    verify_internal_key(x_internal_key)
    return UUID(x_user_id)


@router.get("/internal/", response_model=ApiResponse[list[TagData]], summary="List tags internally")
def internal_list_tags(
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    tags = service.list(db, user_id)
    return success_response([_tag_dict(t) for t in tags], "Tags retrieved")


@router.post("/internal/", response_model=ApiResponse[TagData], summary="Create a tag internally")
def internal_create_tag(
    payload: TagCreate,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    tag = service.create(db, user_id, payload)
    return success_response(_tag_dict(tag), "Tag created")


@router.get("/internal/{tag_id}", response_model=ApiResponse[TagData], summary="Get a tag internally")
def internal_get_tag(
    tag_id: UUID,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    tag = service.get(db, tag_id, user_id)
    return success_response(_tag_dict(tag), "Tag retrieved")


@router.patch("/internal/{tag_id}", response_model=ApiResponse[TagData], summary="Update a tag internally")
def internal_update_tag(
    tag_id: UUID,
    payload: TagUpdate,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    tag = service.update(db, tag_id, user_id, payload)
    return success_response(_tag_dict(tag), "Tag updated")


@router.delete("/internal/{tag_id}", response_model=ApiResponse[None], summary="Delete a tag internally")
def internal_delete_tag(
    tag_id: UUID,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    service.delete(db, tag_id, user_id)
    return success_response(None, "Tag deleted")


@router.get("/{tag_id}", response_model=ApiResponse[TagData], summary="Get a tag")
def get_tag(
    tag_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    """Return one tag owned by the authenticated user."""
    tag = service.get(db, tag_id, current_user.id)
    return success_response(_tag_dict(tag), "Tag retrieved")


@router.patch("/{tag_id}", response_model=ApiResponse[TagData], summary="Update a tag")
def update_tag(
    tag_id: UUID,
    payload: TagUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    """Rename one tag owned by the authenticated user."""
    tag = service.update(db, tag_id, current_user.id, payload)
    return success_response(_tag_dict(tag), "Tag updated")


@router.delete("/{tag_id}", response_model=ApiResponse[None], summary="Delete a tag")
def delete_tag(
    tag_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    """Delete one tag owned by the authenticated user."""
    service.delete(db, tag_id, current_user.id)
    return success_response(None, "Tag deleted")
