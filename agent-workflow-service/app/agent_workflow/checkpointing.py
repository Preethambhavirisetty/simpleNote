from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import MemorySaver


@dataclass
class ManagedCheckpointer:
    checkpointer: Any
    _context: Any = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.checkpointer, name)

    def close(self) -> None:
        close = getattr(self.checkpointer, "close", None)
        if callable(close):
            close()
        if self._context is not None:
            exit_method = getattr(self._context, "__exit__", None)
            if callable(exit_method):
                exit_method(None, None, None)
                self._context = None


def create_checkpointer() -> ManagedCheckpointer:
    mode = (os.getenv("AGENT_WORKFLOW_CHECKPOINTER") or os.getenv("CHECKPOINTER") or "memory").strip().lower()
    if mode in {"", "memory", "dev"}:
        return ManagedCheckpointer(MemorySaver())
    if mode == "redis":
        url = _required_url("AGENT_WORKFLOW_REDIS_URL", "REDIS_URL")
        from langgraph.checkpoint.redis import RedisSaver  # type: ignore[import-not-found]

        return _from_conn_string(RedisSaver, url)
    if mode in {"postgres", "postgresql"}:
        url = _required_url("AGENT_WORKFLOW_POSTGRES_URL", "POSTGRES_URL", "DATABASE_URL")
        from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore[import-not-found]

        saver = _from_conn_string(PostgresSaver, url)
        setup = getattr(saver.checkpointer, "setup", None)
        if callable(setup):
            setup()
        return saver
    raise RuntimeError(f"Unsupported checkpointer mode: {mode}")


def delete_thread(checkpointer: Any, thread_id: str) -> None:
    if not thread_id:
        return
    for method_name in ("delete_thread", "delete", "delete_checkpoint"):
        method = getattr(checkpointer, method_name, None)
        if callable(method):
            for arg in (thread_id, {"configurable": {"thread_id": thread_id}}):
                try:
                    method(arg)
                    return
                except TypeError:
                    continue
                except Exception:
                    return

    target = getattr(checkpointer, "checkpointer", checkpointer)
    for attr in ("storage", "writes", "blobs"):
        store = getattr(target, attr, None)
        if not isinstance(store, dict):
            continue
        for key in list(store.keys()):
            if _key_matches_thread(key, thread_id):
                store.pop(key, None)


def _from_conn_string(cls: Any, url: str) -> ManagedCheckpointer:
    factory = getattr(cls, "from_conn_string", None)
    if not callable(factory):
        return ManagedCheckpointer(cls(url))
    created = factory(url)
    enter = getattr(created, "__enter__", None)
    if callable(enter):
        return ManagedCheckpointer(enter(), created)
    return ManagedCheckpointer(created)


def _required_url(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise RuntimeError(f"Missing checkpointer connection URL. Set one of: {', '.join(names)}")


def _key_matches_thread(key: Any, thread_id: str) -> bool:
    if key == thread_id:
        return True
    if isinstance(key, tuple):
        return any(part == thread_id for part in key)
    if isinstance(key, str):
        return key.startswith(f"{thread_id}:") or key.startswith(f"{thread_id},")
    return False
