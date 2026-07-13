"""Row usability helpers shared by evidence grading (agent-side copy of MCP logic)."""

from __future__ import annotations

import re
from typing import Any

_NA_VALUES = frozenset({"", "-", "na", "n/a", "null", "none", "nan"})
_NUMERIC_FIELD_HINTS = re.compile(
    r"(power|kw|kv|mw|capacity|drawn|available|total|count|usage|percent|%)",
    re.I,
)


def _is_na(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (int, float)):
        return False
    text = str(value).strip()
    if not text:
        return True
    return text.lower() in _NA_VALUES


def _parse_numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().replace(",", "")
    if _is_na(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def row_has_usable_measure(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    for key, value in row.items():
        key_text = str(key)
        if _NUMERIC_FIELD_HINTS.search(key_text) or key_text.lower() in {"value", "metric"}:
            if _parse_numeric(value) is not None:
                return True
    for value in row.values():
        if _parse_numeric(value) is not None:
            return True
    return False


def rows_are_usable(rows: list[dict[str, Any]] | None) -> bool:
    if not isinstance(rows, list) or not rows:
        return False
    return any(row_has_usable_measure(row) for row in rows if isinstance(row, dict))
