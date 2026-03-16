from fastapi import APIRouter, Response, Depends
from app.exceptions.handlers import success_response
from app.schema.users import UserRegisterRequest, UserLoginRequest
from app.services.auth import AuthService
from app.deps.auth import get_current_user


router = APIRouter(prefix="/users", tags=["users"])


def get_auth_service():
    return AuthService()

@router.post("/register")
async def register_user(response: Response, payload: UserRegisterRequest, auth_service: AuthService = Depends(get_auth_service)):
    result = await auth_service.register_user(payload, response)
    return success_response(result, "User registered")

@router.post("/login")
async def login_user(response: Response, payload: UserLoginRequest, auth_service: AuthService = Depends(get_auth_service)):
    result = await auth_service.login_user(payload, response)
    return success_response(result, "User logged in")


@router.delete("/logout/", dependencies=[Depends(get_current_user)])
async def logout(response: Response, auth_service: AuthService = Depends(get_auth_service)):
    result = await auth_service.logout_user(response)
    return success_response(result, "User logged out!")

