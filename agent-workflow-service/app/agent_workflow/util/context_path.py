from __future__ import annotations

from typing import Any


def resolve_context_path(runtime_context: dict[str, Any], path: str) -> Any:
    """Resolve dotted runtime context paths like `tenant.id` safely."""
    if not path:
        return None
    current: Any = runtime_context
    segments = [segment for segment in path.split(".") if segment]
    if len(segments) > 8:
        return None
    for segment in segments:
        if segment in {"__proto__", "constructor", "prototype"}:
            return None
        if not isinstance(current, dict):
            return None
        if segment not in current:
            return None
        current = current.get(segment)
    return current
