from __future__ import annotations

from threading import Lock
from typing import Any

from app.agent_workflow.checkpointing import create_checkpointer

_checkpointer: Any = None
_lock = Lock()


def get_runtime_checkpointer() -> Any:
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    with _lock:
        if _checkpointer is None:
            _checkpointer = create_checkpointer()
        return _checkpointer


def close_runtime_checkpointer() -> None:
    global _checkpointer
    with _lock:
        checkpointer = _checkpointer
        _checkpointer = None
    close = getattr(checkpointer, "close", None)
    if callable(close):
        close()
