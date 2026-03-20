from fastapi import APIRouter

from app.api.v1.endpoints import base, auth, users, folders, notes, tags

api_router = APIRouter(prefix="/api")
api_router.include_router(base.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(folders.router)
api_router.include_router(notes.router)
api_router.include_router(tags.router)
