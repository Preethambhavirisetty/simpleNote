from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.schema.responses import ApiResponse, FolderData

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


@router.get("/", response_model=ApiResponse[list[FolderData]], summary="List folders")
def list_folders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    """List folders owned by the authenticated user."""
    folders = service.list(db, current_user.id, skip=skip, limit=limit)
    return success_response([_folder_dict(f) for f in folders], "Folders retrieved")


@router.post("/", response_model=ApiResponse[FolderData], summary="Create a folder")
def create_folder(
    payload: FolderCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    """Create a folder for the authenticated user."""
    folder = service.create(db, current_user.id, payload)
    return success_response(_folder_dict(folder), "Folder created")


# -- Internal service routes (Agent -> Backend) ------------------------------
# These mirror the cookie-auth folder routes, but authenticate service-to-service
# calls with X-Internal-Key and scope every operation to X-User-Id.

def _internal_user_id(x_internal_key: str, x_user_id: str) -> UUID:
    from app.deps.internal import verify_internal_key

    verify_internal_key(x_internal_key)
    return UUID(x_user_id)


@router.get("/internal/", response_model=ApiResponse[list[FolderData]], summary="List folders internally")
def internal_list_folders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    folders = service.list(db, user_id, skip=skip, limit=limit)
    return success_response([_folder_dict(f) for f in folders], "Folders retrieved")


@router.post("/internal/", response_model=ApiResponse[FolderData], summary="Create a folder internally")
def internal_create_folder(
    payload: FolderCreate,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    folder = service.create(db, user_id, payload)
    return success_response(_folder_dict(folder), "Folder created")


@router.get("/internal/{folder_id}", response_model=ApiResponse[FolderData], summary="Get a folder internally")
def internal_get_folder(
    folder_id: UUID,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    folder = service.get(db, folder_id, user_id)
    return success_response(_folder_dict(folder), "Folder retrieved")


@router.patch("/internal/{folder_id}", response_model=ApiResponse[FolderData], summary="Update a folder internally")
def internal_update_folder(
    folder_id: UUID,
    payload: FolderUpdate,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    folder = service.update(db, folder_id, user_id, payload)
    return success_response(_folder_dict(folder), "Folder updated")


@router.delete("/internal/{folder_id}", response_model=ApiResponse[None], summary="Delete a folder internally")
def internal_delete_folder(
    folder_id: UUID,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    user_id = _internal_user_id(x_internal_key, x_user_id)
    service.delete(db, folder_id, user_id, user_role=["user"])
    return success_response(None, "Folder deleted")


@router.get("/{folder_id}", response_model=ApiResponse[FolderData], summary="Get a folder")
def get_folder(
    folder_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    """Return one folder owned by the authenticated user."""
    folder = service.get(db, folder_id, current_user.id)
    return success_response(_folder_dict(folder), "Folder retrieved")


@router.patch("/{folder_id}", response_model=ApiResponse[FolderData], summary="Update a folder")
def update_folder(
    folder_id: UUID,
    payload: FolderUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    """Update one folder owned by the authenticated user."""
    folder = service.update(db, folder_id, current_user.id, payload)
    return success_response(_folder_dict(folder), "Folder updated")


@router.delete("/{folder_id}", response_model=ApiResponse[None], summary="Delete a folder")
def delete_folder(
    folder_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: FolderService = Depends(get_folder_service),
):
    """Delete one folder owned by the authenticated user."""
    service.delete(db, folder_id, current_user.id, user_role=current_user.role)
    return success_response(None, "Folder deleted")
