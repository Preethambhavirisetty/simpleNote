from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/register",
    "/api/auth/login",
    "/api/feature-flags",
}

OPENAPI_TAGS = [
    {"name": "base", "description": "Backend service health checks."},
    {"name": "auth", "description": "Registration, login, logout, and password management."},
    {"name": "users", "description": "Current-user profile operations and administrator user management."},
    {"name": "folders", "description": "Folder management for the authenticated user."},
    {"name": "notes", "description": "Note CRUD, movement, search, and tag associations."},
    {"name": "tags", "description": "Tag management for the authenticated user."},
    {"name": "conversations", "description": "Chat conversation persistence for the frontend and agent service."},
    {"name": "feature-flags", "description": "Resolved public feature flags."},
]


def configure_openapi(app: FastAPI) -> None:
    """Attach stable Swagger metadata and document existing auth mechanisms."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        security_schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        security_schemes.update({
            "CookieAuth": {
                "type": "apiKey",
                "in": "cookie",
                "name": "access_token",
                "description": "JWT cookie set by POST /api/auth/login.",
            },
            "InternalApiKey": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Internal-Key",
                "description": "Shared key used by the notelite agent service.",
            },
            "InternalUserId": {
                "type": "apiKey",
                "in": "header",
                "name": "X-User-Id",
                "description": "User UUID propagated with internal agent requests.",
            },
        })

        for path, operations in schema.get("paths", {}).items():
            for operation in operations.values():
                if not isinstance(operation, dict):
                    continue
                if path.startswith("/api/conversations/internal"):
                    operation["security"] = [{"InternalApiKey": [], "InternalUserId": []}]
                elif path not in PUBLIC_PATHS:
                    operation["security"] = [{"CookieAuth": []}]

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
