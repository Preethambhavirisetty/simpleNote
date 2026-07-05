from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db.postgres.session import get_postgres_session
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.services.token import TokenService
from app.services.user import UserService

token_service = TokenService()
user_service = UserService()


def get_current_user(
    request: Request,
    db: Session = Depends(get_postgres_session),
):
    token = request.cookies.get('access_token')
    if not token:
        raise AppException(
            message="Invalid or expired cookie",
            status_code=401,
            error_code=ErrorCode.NOT_AUTHENTICATED
        )
    payload = token_service.decode_jwt_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise AppException(
            message="Invalid token payload",
            status_code=401,
            error_code=ErrorCode.UNAUTHORIZED
        )
    user = user_service.get_user(db, user_id)
    if not user.is_active:
        raise AppException(
            message="Account is deactivated",
            status_code=403,
            error_code=ErrorCode.PERMISSION_DENIED
        )
    return user
