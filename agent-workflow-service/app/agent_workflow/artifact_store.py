from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

log = logging.getLogger(__name__)

_KEY_PREFIX = "agent-workflow:session-artifacts:"


def resolve_redis_url() -> str:
    """Return the Redis URL used for cross-turn artifact storage."""
    for name in ("AGENT_WORKFLOW_REDIS_URL", "REDIS_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


class CrossTurnArtifactStore:
    """Persist workflow artifacts per conversation session in Redis."""

    def __init__(self, url: str) -> None:
        self.url = url.strip()
        self._client: Any = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.url)

    def _redis(self) -> Any:
        if not self.url:
            raise RuntimeError("Redis URL is not configured")
        with self._lock:
            if self._client is None:
                import redis

                self._client = redis.Redis.from_url(self.url, decode_responses=True)
            return self._client

    def load(self, session_id: str) -> list[dict[str, Any]]:
        """Load persisted artifacts for a session."""
        session_id = str(session_id or "").strip()
        if not session_id or not self.available:
            return []
        key = f"{_KEY_PREFIX}{session_id}"
        try:
            raw = self._redis().get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("artifact store load failed session=%s error=%s", session_id, exc)
            return []
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("artifact store payload invalid session=%s", session_id)
            return []
        artifacts = payload.get("artifacts") if isinstance(payload, dict) else payload
        if not isinstance(artifacts, list):
            return []
        return [item for item in artifacts if isinstance(item, dict)]

    def save(self, session_id: str, artifacts: list[dict[str, Any]], *, ttl_seconds: int) -> None:
        """Save artifacts for a session with a TTL."""
        session_id = str(session_id or "").strip()
        if not session_id or not self.available:
            return
        key = f"{_KEY_PREFIX}{session_id}"
        payload = {"version": 1, "artifacts": artifacts}
        ttl = max(60, int(ttl_seconds or 86400))
        try:
            self._redis().setex(key, ttl, json.dumps(payload, default=str))
        except Exception as exc:  # noqa: BLE001
            log.warning("artifact store save failed session=%s error=%s", session_id, exc)

    def delete(self, session_id: str) -> None:
        """Remove persisted artifacts for a session."""
        session_id = str(session_id or "").strip()
        if not session_id or not self.available:
            return
        key = f"{_KEY_PREFIX}{session_id}"
        try:
            self._redis().delete(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("artifact store delete failed session=%s error=%s", session_id, exc)


_store: CrossTurnArtifactStore | None = None
_store_lock = threading.Lock()


def get_artifact_store() -> CrossTurnArtifactStore | None:
    """Return a shared artifact store when Redis is configured."""
    global _store
    url = resolve_redis_url()
    if not url:
        return None
    with _store_lock:
        if _store is None or _store.url != url:
            _store = CrossTurnArtifactStore(url)
        return _store


def is_cross_turn_persistence_active(*, enabled: bool) -> bool:
    """Return whether cross-turn persistence is configured and available."""
    return bool(enabled) and bool(resolve_redis_url())
