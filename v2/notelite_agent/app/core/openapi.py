from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


OPENAPI_TAGS = [
    {"name": "health", "description": "Agent service liveness check."},
    {"name": "ingestion", "description": "Queue, run, and inspect note ingestion jobs."},
    {"name": "chat", "description": "Chat completion, retrieval diagnostics, prompt inspection, and SSE streaming."},
    {"name": "prompts", "description": "Internal prompt definition and rendering previews."},
]


def configure_openapi(app: FastAPI) -> None:
    """Attach stable Swagger metadata and document protected prompt routes."""

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
        security_schemes["InternalApiKey"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-Internal-Key",
            "description": "Shared key required by internal prompt administration routes.",
        }

        for path, operations in schema.get("paths", {}).items():
            if not path.startswith("/api/admin/prompts"):
                continue
            for operation in operations.values():
                if isinstance(operation, dict):
                    operation["security"] = [{"InternalApiKey": []}]

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
