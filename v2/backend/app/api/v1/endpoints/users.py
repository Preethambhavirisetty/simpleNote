from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.postgres.session import get_postgres_session
from app.deps.auth import get_current_user
from app.exceptions.base import AppException
from app.exceptions.handlers import success_response
from app.schema.base import ErrorCode
from app.services.user import UserService


router = APIRouter(prefix="/users", tags=["users"])


def get_user_service():
    return UserService()


async def require_admin(current_user=Depends(get_current_user)):
    if "admin" not in current_user.role:
        raise AppException(
            message="Admin access required",
            status_code=403,
            error_code=ErrorCode.PERMISSION_DENIED,
        )
    return current_user


@router.get("/", dependencies=[Depends(require_admin)])
def get_all_users(
    db: Session = Depends(get_postgres_session),
    user_service: UserService = Depends(get_user_service),
):
    results = user_service.list_users(db)
    return success_response(results, "Successfully retrieved all users")


@router.get('/{id}')
def get_user_by_id(
    id: UUID,
    current_user = Depends(get_current_user)
):
    if id != current_user.id:
        raise AppException(
            message="User not found",
            status_code=404,
            error_code=ErrorCode.USER_NOT_FOUND
        )
    return success_response(current_user, "Successfully retrieved user")
