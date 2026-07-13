"""Normalize and repair tool arguments before MCP calls."""

from __future__ import annotations

import json
from typing import Any

_NESTED_WRAPPERS = ("params", "parameters", "arguments", "input")


def normalize_tool_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten common nested wrappers so MCP receives top-level schema fields.

    Models often emit ``{"params": {"panel_id": 77, "panel_tokens": {...}}, "panel_id": 77}``.
    Without flattening, ``panel_tokens`` never reaches the tool and Splunk runs with
    open wildcards while the HTTP call still completes.
    """
    if not isinstance(arguments, dict):
        return {}
    out = dict(arguments)
    for wrapper in _NESTED_WRAPPERS:
        nested = out.pop(wrapper, None)
        if not isinstance(nested, dict):
            continue
        for key, value in nested.items():
            if key == "panel_tokens" and isinstance(value, dict):
                existing = out.get("panel_tokens")
                merged = dict(value)
                if isinstance(existing, dict):
                    merged.update(existing)
                out["panel_tokens"] = merged
            elif key not in out or out.get(key) in (None, "", [], {}):
                out[key] = value
    tokens = out.get("panel_tokens")
    if isinstance(tokens, dict):
        out["panel_tokens"] = {str(k): str(v) for k, v in tokens.items() if v is not None}
    return out


def classify_tool_result_failure(result: Any) -> str | None:
    """Return a human-readable failure reason when a tool payload indicates error."""
    if not isinstance(result, dict):
        return None
    if result.get("ok") is False:
        parts = [str(result.get("error") or "tool returned ok=false").strip()]
        open_filters = result.get("open_filters")
        if isinstance(open_filters, list) and open_filters:
            parts.append(f"open filters: {', '.join(str(x) for x in open_filters)}")
        missing = result.get("missing_tokens")
        if isinstance(missing, list) and missing:
            parts.append(f"missing tokens: {', '.join(str(x) for x in missing)}")
        return "; ".join(part for part in parts if part)
    return None


def _token_catalog_from_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for artifact in reversed(artifacts):
        if str(artifact.get("tool") or "") != "get_dashboard_tokens":
            continue
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        catalog = raw_ref.get("token_catalog")
        if isinstance(catalog, list) and catalog:
            return catalog
    return []


def _catalog_default(catalog: list[dict[str, Any]], token_name: str) -> str | None:
    token_name = (token_name or "").strip()
    if not token_name:
        return None
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        if name.lower() != token_name.lower():
            continue
        default = entry.get("default")
        if default not in (None, ""):
            return str(default)
        values = entry.get("values")
        if isinstance(values, list) and values:
            first = values[0]
            if first not in (None, ""):
                return str(first)
    return None


def _is_open_token_value(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or text == "*"


def build_panel_data_retry_arguments(
    state: dict[str, Any],
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a follow-up get_panel_data call when the prior payload reported open/missing tokens."""
    open_filters = result.get("open_filters")
    missing_tokens = result.get("missing_tokens")
    needs = []
    if isinstance(open_filters, list):
        needs.extend(str(x) for x in open_filters if str(x).strip())
    if isinstance(missing_tokens, list):
        needs.extend(str(x) for x in missing_tokens if str(x).strip())
    if not needs:
        return None

    base = normalize_tool_arguments(arguments)
    panel_tokens = dict(base.get("panel_tokens") or {})
    token_defaults = result.get("token_defaults") if isinstance(result.get("token_defaults"), dict) else {}
    catalog = _token_catalog_from_artifacts(state.get("artifacts") or [])

    for token in needs:
        if not _is_open_token_value(panel_tokens.get(token)):
            continue
        if token in token_defaults and not _is_open_token_value(token_defaults.get(token)):
            panel_tokens[token] = str(token_defaults[token])
            continue
        catalog_default = _catalog_default(catalog, token)
        if catalog_default and not _is_open_token_value(catalog_default):
            panel_tokens[token] = catalog_default

    if not panel_tokens:
        return None
    retry = {**base, "panel_tokens": panel_tokens}
    if json.dumps(retry, sort_keys=True, default=str) == json.dumps(base, sort_keys=True, default=str):
        return None
    return retry
