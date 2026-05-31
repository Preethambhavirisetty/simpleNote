from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel


class HealthData(BaseModel):
    status: str


class PromptDefinition(BaseModel):
    """YAML-backed prompt definition. Prompt-specific fields remain extensible."""

    model_config = ConfigDict(extra="allow")

    version: str
    name: str


class PromptPreviewRequest(RootModel[dict[str, Any]]):
    """Template variables supplied when rendering a prompt preview."""


class PromptPreviewData(RootModel[dict[str, Any]]):
    """Rendered prompt fields returned for deterministic inspection."""
