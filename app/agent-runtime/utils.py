from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


PROMPTS_ROOT = Path(__file__).resolve().parent / "prompts"


class CatalogLookupError(KeyError):
    """The catalog has no such playbook, plan, operation, mapping, or step.

    A run should not continue past a lookup miss: it means the runtime and the
    domain disagree about what exists, which no retry will fix.
    """

    def __str__(self) -> str:  # KeyError's repr quotes the message; this reads better
        return self.args[0] if self.args else ""


class OperationArgumentError(ValueError):
    """Parameters do not satisfy the operation's declared contract."""


# The domain's declared parameter types, as things Python can check. `bool` is
# excluded from integer/number on purpose - in Python `True` is an int, and a
# boolean silently passed as a count is exactly the bug worth catching.
_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


@lru_cache(maxsize=None)
def load_prompt(name: str) -> dict[str, str]:
    """Read `prompts/<name>.yaml`. Prompts are static, so cache them."""
    path = PROMPTS_ROOT / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt not found: {path}")

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid prompt document: {path}")
    return payload


def matches_declared_type(value: Any, declared: str) -> bool:
    expected = _TYPES.get(declared)
    if expected is None:
        return True  # unknown type in the catalog: nothing to check against
    if declared in {"integer", "number"} and isinstance(value, bool):
        return False
    return isinstance(value, expected)
