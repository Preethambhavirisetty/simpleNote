from fastapi.responses import Response
from sqlalchemy.orm import Session
import app.db.postgres.session as pg_session
from app.db.postgres.repos.user import UserRepository
from app.schema.users import UserLoginRequest, UserRegisterRequest, UserCreate, Role
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.core.security import hash_password, check_password
from app.services.token import TokenService


class AuthService:
    def __init__(self):
        self.token_service = TokenService()
        self.user_repo = UserRepository()

    async def register_user(self, db: Session, payload: UserRegisterRequest, response: Response):
        if self.user_repo.get_by_email(db, payload.email):
            raise AppException(
                message="User with this email already exists",
                status_code=400,
                error_code=ErrorCode.REGISTRATION_FAILED,
            )

        role_values = (
            [r.value for r in payload.role]
            if payload.role
            else [Role.STANDARD_USER.value]
        )
        user_data = UserCreate(
            name=payload.name,
            email=payload.email,
            hashed_password=hash_password(payload.password),
            role=role_values,
        )
        new_user = self.user_repo.create(db, user_data)
        db.commit()
        db.refresh(new_user)

        if not self.token_service.create_assign_http_only_cookie(
            response, new_user.id, email=new_user.email, role=new_user.role
        ):
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

    async def login_user(self, db: Session, payload: UserLoginRequest, response: Response):
        existing_user = self.user_repo.get_by_email(db, payload.email)

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

        if not self.token_service.create_assign_http_only_cookie(
            response, existing_user.id, email=existing_user.email, role=existing_user.role
        ):
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
