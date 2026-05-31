from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from jinja2 import StrictUndefined, Template


class PromptError(RuntimeError):
    """Raised when a prompt file is missing or malformed."""


class PromptManager:
    """Load YAML prompts and refresh cached entries when files change."""

    def __init__(self, prompts_dir: str | Path | None = None):
        self.dir = Path(prompts_dir) if prompts_dir else Path(__file__).parent
        self._cache: dict[str, tuple[int, int, dict[str, Any]]] = {}

    def get(self, prompt_name: str) -> dict[str, Any]:
        path = self._path(prompt_name)
        try:
            stat = path.stat()
        except FileNotFoundError as exc:
            raise PromptError(f"Prompt file not found: {prompt_name}") from exc

        cached = self._cache.get(prompt_name)
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        if cached is None or cached[:2] != fingerprint:
            self._cache[prompt_name] = (*fingerprint, self._load(path))
            print(f"prompt for {prompt_name} cached")
        else:
            print(f"Using cached prompt for {prompt_name}")
        return deepcopy(self._cache[prompt_name][2])

    def get_text(self, prompt_name: str, field: str) -> str:
        value = self.get(prompt_name).get(field)
        if not isinstance(value, str) or not value.strip():
            raise PromptError(f"Prompt field is missing or empty: {prompt_name}.{field}")
        return value

    def render_text(self, prompt_name: str, field: str, **variables: Any) -> str:
        return Template(self.get_text(prompt_name, field), undefined=StrictUndefined).render(**variables)

    def render(self, prompt_name: str, **variables: Any) -> dict[str, Any]:
        """Render every text field for deterministic prompt previews."""
        return {
            key: self._render_value(value, variables)
            for key, value in self.get(prompt_name).items()
        }

    def _path(self, prompt_name: str) -> Path:
        if not prompt_name or Path(prompt_name).name != prompt_name:
            raise PromptError("Prompt name must be a file stem without path separators.")
        return self.dir / f"{prompt_name}.yaml"

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        try:
            prompt = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PromptError(f"Invalid YAML in prompt file: {path.name}") from exc
        if not isinstance(prompt, dict):
            raise PromptError(f"Prompt file must contain a YAML mapping: {path.name}")
        return prompt

    @classmethod
    def _render_value(cls, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return Template(value, undefined=StrictUndefined).render(**variables)
        if isinstance(value, dict):
            return {key: cls._render_value(item, variables) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._render_value(item, variables) for item in value]
        return value


prompt_manager = PromptManager()
