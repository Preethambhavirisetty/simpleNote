"""The failure catalog is duplicated per service; this fails when they drift.

Why copies rather than one imported module: the services do not share a Python
path. Importing across them would mean mounting `app/shared` into every
container and setting PYTHONPATH, and a missing mount would then stop a service
from *booting* - a worse failure than the drift it prevents. A byte-comparison
test catches drift with no runtime coupling at all.

Run from the repo root:

    python -m pytest app/shared/test_failures_in_sync.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "failures.py"
COPIES = (
    Path("app/agent-runtime/failures.py"),
    Path("app/orchestrator/app/shared/failures.py"),
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_service_copy_matches_the_source() -> None:
    expected = _digest(SOURCE)
    drifted = []
    for relative in COPIES:
        copy = REPO_ROOT / relative
        if not copy.is_file():
            drifted.append(f"{relative} is missing")
        elif _digest(copy) != expected:
            drifted.append(f"{relative} differs from app/shared/failures.py")

    assert not drifted, (
        "The failure catalog has drifted. Re-copy it:\n  "
        + "\n  ".join(f"cp app/shared/failures.py {relative}" for relative in COPIES)
        + "\n\n"
        + "\n".join(drifted)
    )


def test_catalog_is_self_consistent() -> None:
    """Every entry is reachable by its own code, and codes are unique."""
    import sys

    sys.path.insert(0, str(SOURCE.parent))
    import failures

    for code, failure in failures.CATALOG.items():
        assert failure.code == code, f"{code} is registered under the wrong key"
        assert failures.get(code) is failure
        assert failure.message.strip(), f"{code} has no user-facing message"

    assert failures.get("NO_SUCH_CODE") is failures.INTERNAL_ERROR
