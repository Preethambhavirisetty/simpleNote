"""Feature flag loader with automatic refresh when feature_flags.json changes.

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
import threading
from typing import Any

from fastapi import HTTPException

log = logging.getLogger(__name__)

_FLAGS_PATH = os.getenv(
    "FEATURE_FLAGS_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "feature_flags.json"),
)

_flags: dict[str, Any] = {}
_flags_lock = threading.RLock()
_flags_source_path = _FLAGS_PATH
_flags_resolved_path = os.path.realpath(_FLAGS_PATH)
_flags_signature: tuple[int, int, int] | object | None = None
_MISSING_FILE = object()


def _file_signature(file_stat: os.stat_result) -> tuple[int, int, int]:
    return (file_stat.st_ino, file_stat.st_size, file_stat.st_mtime_ns)


def load_flags(path: str | None = None) -> dict[str, Any]:
    global _flags, _flags_resolved_path, _flags_signature, _flags_source_path

    source_path = path or _FLAGS_PATH
    resolved = os.path.realpath(source_path)
    with _flags_lock:
        try:
            with open(resolved, "r") as f:
                loaded_flags = json.load(f)
                signature = _file_signature(os.fstat(f.fileno()))
        except FileNotFoundError:
            log.warning("Feature flags file not found at %s — all flags default to disabled", resolved)
            loaded_flags = {}
            signature = _MISSING_FILE
        except (OSError, json.JSONDecodeError):
            log.exception("Unable to refresh feature flags from %s — keeping last valid values", resolved)
            return _flags

        _flags = loaded_flags
        _flags_source_path = source_path
        _flags_resolved_path = resolved
        _flags_signature = signature
        log.info("Feature flags loaded from %s", resolved)
        return _flags


def _refresh_flags_if_changed() -> None:
    resolved = os.path.realpath(_flags_source_path)
    try:
        signature: tuple[int, int, int] | object = _file_signature(os.stat(resolved))
    except FileNotFoundError:
        signature = _MISSING_FILE
    except OSError:
        log.exception("Unable to check feature flags at %s — keeping last valid values", resolved)
        return

    with _flags_lock:
        if resolved != _flags_resolved_path or signature != _flags_signature:
            load_flags(_flags_source_path)


def is_enabled(key: str) -> bool:
    """Check whether a (possibly nested) feature is enabled.

    Examples:
        is_enabled("chat")           -> chat.enabled
        is_enabled("chat.streaming") -> chat.enabled AND chat.children.streaming.enabled
    """
    _refresh_flags_if_changed()
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


def get_all_resolved() -> dict[str, bool]:
    """Return a flat map of every flag with its resolved boolean value."""
    _refresh_flags_if_changed()
    result: dict[str, bool] = {}

    for key, node in _flags.items():
        if not isinstance(node, dict):
            continue
        parent_on = bool(node.get("enabled", False))
        result[key] = parent_on
        for child_key, child_node in node.get("children", {}).items():
            if isinstance(child_node, dict):
                result[f"{key}.{child_key}"] = parent_on and bool(child_node.get("enabled", False))

    return result


def require_feature(flag_key: str):
    """FastAPI dependency factory — returns 404 when the flag is off."""

    def _guard():
        if not is_enabled(flag_key):
            raise HTTPException(status_code=404, detail="Not found")

    return _guard


# Load initially; subsequent reads refresh automatically when the file changes.
load_flags()
