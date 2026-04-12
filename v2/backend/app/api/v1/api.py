from fastapi import APIRouter

from app.api.v1.endpoints import auth, base, conversations, feature_flags, folders, notes, tags, users

api_router = APIRouter(prefix="/api")
api_router.include_router(base.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(folders.router)
api_router.include_router(notes.router)
api_router.include_router(tags.router)
api_router.include_router(conversations.router)
api_router.include_router(feature_flags.router)
