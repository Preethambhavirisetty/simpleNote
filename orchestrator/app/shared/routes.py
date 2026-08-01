from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.internal_auth import verify_internal_key
from app.shared.api_models import PromptDefinition, PromptPreviewData, PromptPreviewRequest
from app.shared.prompts.prompt_manager import PromptError, prompt_manager
from app.shared.schema import ApiResponse


def require_internal_key(
    x_internal_key: str | None = Header(default=None, alias="X-Internal-Key"),
) -> None:
    verify_internal_key(x_internal_key)


router = APIRouter(
    prefix="/api/admin/prompts",
    tags=["prompts"],
    dependencies=[Depends(require_internal_key)],
)


@router.get("/{name}", response_model=ApiResponse[PromptDefinition], summary="Get a prompt definition")
def get_prompt(name: str):
    """Return the current YAML prompt definition."""
    try:
        return ApiResponse.ok(prompt_manager.get(name))
    except PromptError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{name}/preview", response_model=ApiResponse[PromptPreviewData], summary="Preview a rendered prompt")
def preview_prompt(name: str, variables: PromptPreviewRequest):
    """Render a prompt definition without calling an LLM."""
    try:
        return ApiResponse.ok(prompt_manager.render(name, **variables.root))
    except PromptError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Prompt rendering failed: {exc}") from exc
