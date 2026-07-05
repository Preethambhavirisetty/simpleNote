from __future__ import annotations

import ast
from pathlib import Path


def _is_allowed(import_name: str) -> bool:
    if import_name == "app":
        return False
    if import_name.startswith("app.agent_workflow"):
        return True
    return not import_name.startswith("app.")


def test_no_external_app_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []

    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in {"tests", "adapters"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not _is_allowed(alias.name):
                        violations.append(f"{relative}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level != 0:
                    continue
                if module and not _is_allowed(module):
                    violations.append(f"{relative}: from {module} import ...")

    assert not violations, "Found non-decoupled imports:\n" + "\n".join(sorted(violations))
