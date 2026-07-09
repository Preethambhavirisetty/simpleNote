from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import yaml

ProfileMode = Literal["quick", "heavy"]

_PROFILES_DIR = Path(__file__).resolve().parent / "agents" / "profiles"
_VALID_PROFILES = frozenset({"quick", "heavy"})


def normalize_exploration_profile(value: Any) -> ProfileMode | None:
    """Map caller/env values to a supported exploration profile."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"quick", "quick-read", "fast"}:
        return "quick"
    if text in {"heavy", "heavy-explore", "deep"}:
        return "heavy"
    return None


def resolve_exploration_profile(
    runtime_context: dict[str, Any] | None,
    *,
    env_default: str | None = None,
) -> ProfileMode:
    """Resolve profile: request runtime_context beats env, then quick."""
    ctx = runtime_context or {}
    explicit = normalize_exploration_profile(ctx.get("exploration_profile"))
    if explicit:
        return explicit
    env_value = env_default if env_default is not None else os.getenv("DEFAULT_EXPLORATION_PROFILE", "quick")
    return normalize_exploration_profile(env_value) or "quick"


def profile_policy_overrides(mode: ProfileMode) -> dict[str, Any]:
    """Load a profile preset as runtime override fragments."""
    filename = "quick-read.yaml" if mode == "quick" else "heavy-explore.yaml"
    path = _PROFILES_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Exploration profile preset not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    policy = raw.get("policy") if isinstance(raw.get("policy"), dict) else raw
    if not isinstance(policy, dict):
        return {}
    return {"policy": deepcopy(policy)}


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = deepcopy(value)
    return merged


def apply_exploration_profile_to_overrides(
    overrides: dict[str, Any],
    runtime_context: dict[str, Any] | None,
    *,
    env_default: str | None = None,
) -> ProfileMode:
    """Merge the resolved exploration preset UNDER the caller's runtime overrides.

    Precedence is default config < mode profile < explicit caller overrides:
    the profile sets the baseline for the chosen mode, but any key the caller
    set explicitly (in a request or runtime bundle) wins, so an explicit tweak
    is never silently clobbered by the mode preset.
    """
    mode = resolve_exploration_profile(runtime_context, env_default=env_default)
    preset = profile_policy_overrides(mode)
    if preset:
        merged = _deep_merge(preset, overrides)
        overrides.clear()
        overrides.update(merged)
    return mode


def validate_runtime_context_profile(runtime_context: dict[str, Any]) -> dict[str, Any]:
    """Normalize exploration_profile when present; raise on invalid values."""
    if "exploration_profile" not in runtime_context:
        return runtime_context
    normalized = normalize_exploration_profile(runtime_context.get("exploration_profile"))
    if normalized is None:
        raise ValueError("runtime_context.exploration_profile must be 'quick' or 'heavy'")
    cleaned = dict(runtime_context)
    cleaned["exploration_profile"] = normalized
    return cleaned
