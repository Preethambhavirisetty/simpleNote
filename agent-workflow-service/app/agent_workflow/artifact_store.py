from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

log = logging.getLogger(__name__)

_KEY_PREFIX = "agent-workflow:session-artifacts:"
# Cap the no-Redis fallback so a long-lived process serving many sessions does
# not grow the in-process map without bound (Redis paths expire via TTL).
_MAX_LOCAL_SESSIONS = 2000


def resolve_redis_url() -> str:
    """Return the Redis URL used for cross-turn artifact storage."""
    for name in ("AGENT_WORKFLOW_REDIS_URL", "REDIS_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


class CrossTurnArtifactStore:
    """Persist workflow artifacts per conversation session.

    Redis-backed when a URL is configured; otherwise an in-process fallback so
    cross-turn evidence reuse still works in dev/single-instance deployments
    (mirroring ConversationMemoryStore). The in-process map is bounded and
    process-local — use Redis for multi-worker setups.
    """

    def __init__(self, url: str) -> None:
        self.url = url.strip()
        self._client: Any = None
        self._lock = threading.Lock()
        self._local: dict[str, list[dict[str, Any]]] = {}

    @property
    def available(self) -> bool:
        """Whether a Redis backend is configured (the fallback is always usable)."""
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
        if not session_id:
            return []
        if not self.available:
            with self._lock:
                return list(self._local.get(session_id) or [])
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
        if not session_id:
            return
        if not self.available:
            with self._lock:
                # Refresh recency (move to newest) then evict oldest over the cap.
                self._local.pop(session_id, None)
                self._local[session_id] = list(artifacts or [])
                while len(self._local) > _MAX_LOCAL_SESSIONS:
                    self._local.pop(next(iter(self._local)))
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
        if not session_id:
            return
        if not self.available:
            with self._lock:
                self._local.pop(session_id, None)
            return
        key = f"{_KEY_PREFIX}{session_id}"
        try:
            self._redis().delete(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("artifact store delete failed session=%s error=%s", session_id, exc)


_store: CrossTurnArtifactStore | None = None
_store_lock = threading.Lock()


def get_artifact_store() -> CrossTurnArtifactStore:
    """Return the shared artifact store (Redis when configured, else in-process)."""
    global _store
    url = resolve_redis_url()
    with _store_lock:
        if _store is None or _store.url != url:
            _store = CrossTurnArtifactStore(url)
        return _store


def is_cross_turn_persistence_active(*, enabled: bool) -> bool:
    """Return whether cross-turn persistence is enabled.

    The store always has a working backend (Redis or the bounded in-process
    fallback), so activation is purely the config flag now.
    """
    return bool(enabled)
