from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.postgres.session import get_postgres_session
from app.deps.auth import get_current_user
from app.exceptions.handlers import success_response
from app.schema.users import UserChangePassword, UserLoginRequest, UserRegisterRequest
from app.services.auth import AuthService
from app.services.user import UserService

router = APIRouter(prefix='/auth', tags=["auth"])


def get_auth_service():
    return AuthService()


def get_user_service():
    return UserService()


@router.post("/register")
async def register_user(
    response: Response,
    payload: UserRegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_postgres_session)
):
    result = await auth_service.register_user(db, payload, response)
    return success_response(result, "User registered")


@router.post("/login")
async def login_user(
    response: Response,
    payload: UserLoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_postgres_session)
):
    result = await auth_service.login_user(db, payload, response)
    return success_response(result, "User logged in")


@router.delete("/logout/", dependencies=[Depends(get_current_user)])
async def logout(response: Response, auth_service: AuthService = Depends(get_auth_service)):
    result = await auth_service.logout_user(response)
    return success_response(result, "User logged out!")


@router.patch('/change-password')
async def change_password(
    payload: UserChangePassword,
    current_user = Depends(get_current_user),
    user_service = Depends(get_user_service),
    db: Session = Depends(get_postgres_session)
):
    result = user_service.change_password(db, current_user.id, payload)
    return success_response(result, "Password changed successfully")

