"""
Canonical schema for the Celery ingestion task payload.

This is the single source of truth for what the ingestion worker receives.
Both the backend (producer) and the worker (consumer) must conform to this contract.

Field contract
──────────────
Producer (backend)     → Consumer (agent)   Notes
─────────────────────────────────────────────────────────────────────────────
userid                 → user_id            Renamed by @model_validator
user_id                → user_id            Accepted as-is
role (list[str])       → role (str)         First element taken; default "user"
text                   → text               Plain text extracted from note content
action                 → action             Lowercased; "upsert" or "delete"
version (int | None)   → version            None = no guard (direct API calls)
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class IngestionTaskPayload(BaseModel):
    """Validated, normalised payload entering the ingestion worker."""

    user_id: str
    note_id: str = "UNKNOWN_NOTE"
    folder_id: str = "UNKNOWN_FOLDER"
    role: str = "user"
    tenant_id: Optional[str] = None
    folder_title: str = "Untitled Folder"
    note_title: str = "Untitled Note"
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    # Plain text content of the note — the field the chunking pipeline uses.
    text: str = ""
    # "upsert" or "delete"
    action: str = "upsert"
    # None means "no version guard" (e.g. task came from the direct /ingest HTTP endpoint).
    # An integer is the version at dispatch time; worker skips if it's behind the DB.
    version: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: dict) -> dict:
        # userid (BE naming) → user_id (pipeline naming)
        if "userid" in data and "user_id" not in data:
            data["user_id"] = data.pop("userid")

        # role can arrive as a list from the backend — take first element
        role = data.get("role")
        if isinstance(role, list):
            data["role"] = role[0] if role else "user"

        # normalise action to lowercase
        if "action" in data:
            data["action"] = str(data["action"]).strip().lower()

        return data

    class Config:
        # Silently ignore extra fields (e.g. future BE additions don't break older workers)
        extra = "ignore"
