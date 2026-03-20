from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.postgres.models.user import User
from app.db.postgres.session import get_postgres_session
from app.deps.auth import get_current_user
from app.exceptions.base import AppException
from app.exceptions.handlers import success_response
from app.schema.base import ErrorCode
from app.schema.users import UserAssignRoles, UserUpdate
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])


def get_user_service():
    return UserService()


def _user_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


async def require_admin(current_user=Depends(get_current_user)):
    if "admin" not in current_user.role:
        raise AppException(
            message="Admin access required",
            status_code=403,
            error_code=ErrorCode.PERMISSION_DENIED,
        )
    return current_user


# ── Own profile ───────────────────────────────────────────────────────────────

@router.get("/me")
def get_me(current_user=Depends(get_current_user)):
    return success_response(_user_dict(current_user), "User retrieved")


@router.patch("/me")
def update_me(
    payload: UserUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    updated = user_service.update_user(db, current_user.id, payload)
    return success_response(_user_dict(updated), "Profile updated")


@router.delete("/me")
def delete_me(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    user_service.delete_user(db, current_user.id)
    return success_response(None, "Account deleted")


# ── Admin: any user ───────────────────────────────────────────────────────────

@router.get("/", dependencies=[Depends(require_admin)])
def get_all_users(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    users = user_service.list_users(db, skip=skip, limit=limit)
    return success_response([_user_dict(u) for u in users], "Users retrieved")


@router.get("/{user_id}", dependencies=[Depends(require_admin)])
def get_user(
    user_id: UUID,
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    user = user_service.get_user(db, user_id)
    return success_response(_user_dict(user), "User retrieved")


@router.patch("/{user_id}", dependencies=[Depends(require_admin)])
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    updated = user_service.update_user(db, user_id, payload)
    return success_response(_user_dict(updated), "User updated")


@router.delete("/{user_id}", dependencies=[Depends(require_admin)])
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    user_service.delete_user(db, user_id)
    return success_response(None, "User deleted")


@router.patch("/{user_id}/roles", dependencies=[Depends(require_admin)])
def assign_roles(
    user_id: UUID,
    payload: UserAssignRoles,
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    updated = user_service.assign_roles(db, user_id, payload)
    return success_response(_user_dict(updated), "Roles updated")


@router.patch("/{user_id}/activate", dependencies=[Depends(require_admin)])
def activate_user(
    user_id: UUID,
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    user_service.activate_user(db, user_id)
    return success_response(None, "User activated")


@router.patch("/{user_id}/deactivate", dependencies=[Depends(require_admin)])
def deactivate_user(
    user_id: UUID,
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    user_service.deactivate_user(db, user_id)
    return success_response(None, "User deactivated")
