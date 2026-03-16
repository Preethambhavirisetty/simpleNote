from fastapi import Request
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.services.token import TokenService
from app.services.user import UserService

token_service = TokenService()
user_service = UserService()

async def get_current_user(request: Request):
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
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise AppException(
            message="User not found",
            status_code=404,
            error_code=ErrorCode.USER_NOT_FOUND
        )
    return user