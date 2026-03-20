from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

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


@router.get("/")
def list_tags(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    tags = service.list(db, current_user.id)
    return success_response([_tag_dict(t) for t in tags], "Tags retrieved")


@router.post("/")
def create_tag(
    payload: TagCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    tag = service.create(db, current_user.id, payload)
    return success_response(_tag_dict(tag), "Tag created")


@router.get("/{tag_id}")
def get_tag(
    tag_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    tag = service.get(db, tag_id, current_user.id)
    return success_response(_tag_dict(tag), "Tag retrieved")


@router.patch("/{tag_id}")
def update_tag(
    tag_id: UUID,
    payload: TagUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    tag = service.update(db, tag_id, current_user.id, payload)
    return success_response(_tag_dict(tag), "Tag updated")


@router.delete("/{tag_id}")
def delete_tag(
    tag_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: TagService = Depends(get_tag_service),
):
    service.delete(db, tag_id, current_user.id)
    return success_response(None, "Tag deleted")
