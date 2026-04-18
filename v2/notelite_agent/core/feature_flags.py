"""Feature flag loader — reads feature_flags.json once on import.

The config file uses a nested structure:

    {
      "chat": {
        "enabled": false,
        "children": {
          "streaming": { "enabled": true },
          "history":   { "enabled": true }
        }
      }
    }

Resolution: ``is_enabled("chat.streaming")`` is True only when **both**
``chat.enabled`` and ``chat.children.streaming.enabled`` are True.
"""

import json
import logging
import os
from typing import Any

from fastapi import HTTPException

log = logging.getLogger(__name__)

_FLAGS_PATH = os.getenv(
    "FEATURE_FLAGS_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "feature_flags.json"),
)

_flags: dict[str, Any] = {}


def load_flags(path: str | None = None) -> dict[str, Any]:
    global _flags
    path = path or _FLAGS_PATH
    resolved = os.path.realpath(path)
    try:
        with open(resolved, "r") as f:
            _flags = json.load(f)
        log.info("Feature flags loaded from %s", resolved)
    except FileNotFoundError:
        log.warning("Feature flags file not found at %s — all flags default to disabled", resolved)
        _flags = {}
    return _flags


def is_enabled(key: str) -> bool:
    """Check whether a (possibly nested) feature is enabled.

    Examples:
        is_enabled("chat")           → chat.enabled
        is_enabled("chat.streaming") → chat.enabled AND chat.children.streaming.enabled
    """
    parts = key.split(".")
    node = _flags.get(parts[0])
    if not isinstance(node, dict) or not node.get("enabled", False):
        return False
    for part in parts[1:]:
        children = node.get("children", {})
        node = children.get(part)
        if not isinstance(node, dict) or not node.get("enabled", False):
            return False
    return True


def toggle_flag(name: str, mode: bool) -> bool:
    """Toggle a feature flag by name (root or child) and persist to disk.

    Returns True if the flag was found and updated, False otherwise.
    """
    from core.feature_flags import _FLAGS_PATH, load_flags

    resolved = os.path.realpath(_FLAGS_PATH)
    with open(resolved, "r") as f:
        flags = json.load(f)

    for root, data in flags.items():
        if root == name:
            data["enabled"] = mode
            break
        for child_name, child_data in data.get("children", {}).items():
            if child_name == name:
                child_data["enabled"] = mode
                break
        else:
            continue
        break
    else:
        return False

    with open(resolved, "w") as f:
        json.dump(flags, f, indent=4)

    load_flags(resolved)
    return True



def require_feature(flag_key: str):
    """FastAPI dependency factory — returns 404 when the flag is off."""

    def _guard():
        if not is_enabled(flag_key):
            raise HTTPException(status_code=404, detail="Not found")

    return _guard


# Load on import so flags are ready before any route is registered.
load_flags()
