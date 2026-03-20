from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.postgres.models.folder import Folder
from app.db.postgres.session import get_postgres_session
from app.deps.auth import get_current_user
from app.exceptions.handlers import success_response
from app.schema.folder import FolderCreate, FolderUpdate
from app.services.folders import FolderService


router = APIRouter(prefix="/folders", tags=["folders"])


def get_folder_service():
    return FolderService()


def _folder_dict(folder: Folder) -> dict:
    return {
        "id": str(folder.id),
        "user_id": str(folder.user_id),
        "name": folder.name,
        "is_pinned": folder.is_pinned,
        "created_at": folder.created_at.isoformat(),
        "updated_at": folder.updated_at.isoformat(),
    }


@router.get("/")
def list_folders(
    skip: int = 0,
    limit: int = 50,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    folders = service.list(db, current_user.id, skip=skip, limit=limit)
    return success_response([_folder_dict(f) for f in folders], "Folders retrieved")


@router.post("/")
def create_folder(
    payload: FolderCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    folder = service.create(db, current_user.id, payload)
    return success_response(_folder_dict(folder), "Folder created")


@router.get("/{folder_id}")
def get_folder(
    folder_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    folder = service.get(db, folder_id, current_user.id)
    return success_response(_folder_dict(folder), "Folder retrieved")


@router.patch("/{folder_id}")
def update_folder(
    folder_id: UUID,
    payload: FolderUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    folder = service.update(db, folder_id, current_user.id, payload)
    return success_response(_folder_dict(folder), "Folder updated")


@router.delete("/{folder_id}")
def delete_folder(
    folder_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    service.delete(db, folder_id, current_user.id)
    return success_response(None, "Folder deleted")
