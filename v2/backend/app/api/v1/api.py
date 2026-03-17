from fastapi import APIRouter

from app.api.v1.endpoints import base, auth, users

api_router = APIRouter(prefix="/api")
api_router.include_router(base.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
