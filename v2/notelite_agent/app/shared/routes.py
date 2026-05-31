from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import AGENT_API_KEY
from app.shared.prompts.prompt_manager import PromptError, prompt_manager
from app.shared.schema import ApiResponse


def require_internal_key(
    x_internal_key: str | None = Header(default=None, alias="X-Internal-Key"),
) -> None:
    if x_internal_key is None or not secrets.compare_digest(x_internal_key, AGENT_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal API key.")


router = APIRouter(
    prefix="/api/admin/prompts",
    tags=["prompts"],
    dependencies=[Depends(require_internal_key)],
)


@router.get("/{name}", response_model=ApiResponse[dict])
def get_prompt(name: str):
    """Return the current YAML prompt definition."""
    try:
        return ApiResponse.ok(prompt_manager.get(name))
    except PromptError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{name}/preview", response_model=ApiResponse[dict])
def preview_prompt(name: str, variables: dict[str, Any]):
    """Render a prompt definition without calling an LLM."""
    try:
        return ApiResponse.ok(prompt_manager.render(name, **variables))
    except PromptError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Prompt rendering failed: {exc}") from exc
