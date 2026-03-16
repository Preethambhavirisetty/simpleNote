from fastapi.responses import Response
from sqlalchemy import select

from app.db.postgres.models.user import User
import app.db.postgres.session as pg_session
from app.schema.users import UserLoginRequest, UserRegisterRequest, Role
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.core.security import hash_password, check_password
from app.services.token import TokenService


class AuthService:
    def __init__(self):
        self.token_service = TokenService()

    def _get_session(self):
        if pg_session.SessionLocal is None:
            raise AppException(
                message="Postgres is not configured",
                status_code=500,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            )
        return pg_session.SessionLocal()

    async def register_user(self, payload: UserRegisterRequest, response: Response):
        with self._get_session() as db:
            existing = db.execute(
                select(User).where(User.email == payload.email)
            ).scalar_one_or_none()
            if existing:
                raise AppException(
                    message="User with this email already exists",
                    status_code=400,
                    error_code=ErrorCode.REGISTRATION_FAILED,
                )

            hashed_password = hash_password(payload.password)
            role_values = (
                [r.value for r in payload.role]
                if payload.role
                else [Role.STANDARD_USER.value]
            )
            new_user = User(
                name=payload.name,
                email=payload.email,
                hashed_password=hashed_password,
                role=role_values,
            )
            db.add(new_user)
            db.commit()
            db.refresh(new_user)

        if not self.token_service.create_assign_http_only_cookie(response, new_user.id):
            raise AppException(
                message="Error occurred while setting cookie",
                status_code=400,
                error_code=ErrorCode.REGISTRATION_FAILED,
            )
        return {
            "name": new_user.name,
            "email": new_user.email,
            "role": new_user.role,
            "is_active": new_user.is_active,
        }

    async def login_user(self, payload: UserLoginRequest, response: Response):
        with self._get_session() as db:
            existing_user = db.execute(
                select(User).where(User.email == payload.email)
            ).scalar_one_or_none()

        if not existing_user:
            raise AppException(
                message="Invalid email or password",
                status_code=400,
                error_code=ErrorCode.INVALID_CREDENTIALS,
            )

        if not check_password(payload.password, existing_user.hashed_password):
            raise AppException(
                message="Invalid email or password",
                status_code=400,
                error_code=ErrorCode.INVALID_CREDENTIALS,
            )

        if not self.token_service.create_assign_http_only_cookie(response, existing_user.id):
            raise AppException(
                message="Error occurred while setting cookie",
                status_code=400,
                error_code=ErrorCode.REGISTRATION_FAILED,
            )
        return {
            "name": existing_user.name,
            "email": existing_user.email,
            "role": existing_user.role,
            "is_active": existing_user.is_active,
        }

    async def logout_user(self, response: Response):
        try:
            response.delete_cookie("access_token")
            return {"message": "successfully deleted cookie"}
        except Exception:
            raise AppException(
                message="Failed to delete cookie",
                status_code=400,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            )
