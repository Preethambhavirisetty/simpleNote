from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any

from app.agent_workflow.artifact_store import resolve_redis_url

log = logging.getLogger(__name__)

_KEY_PREFIX = "agent-workflow:session-memory:"

# Argument names that usually carry free-text (the request itself), not a stable
# entity worth remembering as a conversation preference.
_FREEFORM_ARG_KEYS = frozenset(
    {"query", "q", "text", "prompt", "content", "message", "body", "spl", "sql",
     "question", "search", "input", "filter", "expr"}
)
_MAX_SLOT_KEY_CHARS = 40
_MAX_SLOT_VALUE_CHARS = 120
_MAX_FINDING_CHARS = 240
# Cap the no-Redis fallback so a long-lived process serving many sessions does
# not grow the in-process map without bound (Redis paths expire via TTL).
_MAX_LOCAL_SESSIONS = 2000


# ── slot store ───────────────────────────────────────────────────────────────
class ConversationMemoryStore:
    """Per-conversation slot memory. Redis-backed when configured, else in-process.

    Stores a small ``{slot: {value, finding, turn, tool}}`` map per session so
    follow-up turns can resolve terse references (e.g. "it") to the entity the
    conversation established. The in-process fallback keeps the feature working
    in single-instance/dev/test setups without Redis.
    """

    def __init__(self, url: str = "") -> None:
        self.url = url.strip()
        self._client: Any = None
        self._lock = threading.Lock()
        self._local: dict[str, dict[str, Any]] = {}

    @property
    def uses_redis(self) -> bool:
        return bool(self.url)

    def _redis(self) -> Any:
        with self._lock:
            if self._client is None:
                import redis

                self._client = redis.Redis.from_url(self.url, decode_responses=True)
            return self._client

    def load(self, session_id: str) -> dict[str, Any]:
        """Load the slot map for a session (empty when unknown)."""
        session_id = str(session_id or "").strip()
        if not session_id:
            return {}
        if not self.uses_redis:
            with self._lock:
                return dict(self._local.get(session_id) or {})
        key = f"{_KEY_PREFIX}{session_id}"
        try:
            raw = self._redis().get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("conversation memory load failed session=%s error=%s", session_id, exc)
            return {}
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("conversation memory payload invalid session=%s", session_id)
            return {}
        slots = payload.get("slots") if isinstance(payload, dict) else payload
        return slots if isinstance(slots, dict) else {}

    def save(self, session_id: str, slots: dict[str, Any], *, ttl_seconds: int) -> None:
        """Persist the slot map for a session with a TTL."""
        session_id = str(session_id or "").strip()
        if not session_id:
            return
        if not self.uses_redis:
            with self._lock:
                # Refresh recency (move to newest) then evict oldest over the cap.
                self._local.pop(session_id, None)
                self._local[session_id] = dict(slots or {})
                while len(self._local) > _MAX_LOCAL_SESSIONS:
                    self._local.pop(next(iter(self._local)))
            return
        key = f"{_KEY_PREFIX}{session_id}"
        payload = {"version": 1, "slots": slots}
        ttl = max(60, int(ttl_seconds or 86400))
        try:
            self._redis().setex(key, ttl, json.dumps(payload, default=str))
        except Exception as exc:  # noqa: BLE001
            log.warning("conversation memory save failed session=%s error=%s", session_id, exc)

    def delete(self, session_id: str) -> None:
        """Remove a session's slot memory."""
        session_id = str(session_id or "").strip()
        if not session_id:
            return
        if not self.uses_redis:
            with self._lock:
                self._local.pop(session_id, None)
            return
        try:
            self._redis().delete(f"{_KEY_PREFIX}{session_id}")
        except Exception as exc:  # noqa: BLE001
            log.warning("conversation memory delete failed session=%s error=%s", session_id, exc)


_store: ConversationMemoryStore | None = None
_store_lock = threading.Lock()


def get_memory_store() -> ConversationMemoryStore:
    """Return the shared conversation-memory store (Redis if configured)."""
    global _store
    url = resolve_redis_url()
    with _store_lock:
        if _store is None or _store.url != url:
            _store = ConversationMemoryStore(url)
        return _store


# ── extraction / rendering ───────────────────────────────────────────────────
def _slot_value(value: Any) -> str:
    """Return a short, entity-like string for a slot value, or '' to skip it."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        if not text or len(text) > _MAX_SLOT_VALUE_CHARS:
            return ""
        return text
    return ""  # dicts/lists are not stable single-entity preferences


_SCALAR_ARG_RE = re.compile(
    r'"([^"]{1,%d})"\s*:\s*(?:"([^"]{1,%d})"|(-?\d+(?:\.\d+)?))'
    % (_MAX_SLOT_KEY_CHARS, _MAX_SLOT_VALUE_CHARS)
)


def _parse_args(args_preview: Any) -> dict[str, Any]:
    """Best-effort parse of a tool call's argument preview into a dict.

    Tool-call records store ``args_preview`` as a length-capped JSON string, so a
    call with large arguments serializes to invalid (truncated) JSON. Rather than
    drop every slot from that call, fall back to scanning the preview for
    top-level ``"key": scalar`` pairs — enough to recover the short entity args
    the memory feature exists to capture.
    """
    if isinstance(args_preview, dict):
        return args_preview
    if not isinstance(args_preview, str) or not args_preview.strip():
        return {}
    try:
        parsed = json.loads(args_preview)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        recovered: dict[str, Any] = {}
        for key, str_val, num_val in _SCALAR_ARG_RE.findall(args_preview):
            recovered[key] = str_val if str_val else num_val
        return recovered


def _first_line(text: Any) -> str:
    for line in str(text or "").splitlines():
        line = line.strip()
        if line:
            return line[:_MAX_FINDING_CHARS]
    return ""


def _finding_for(call: dict[str, Any], artifacts: list[dict[str, Any]]) -> str:
    """Pick a one-line finding from the artifact produced by this tool call."""
    name = call.get("name")
    step_index = call.get("step_index")
    best = None
    for artifact in artifacts:
        if artifact.get("tool") != name:
            continue
        if step_index is not None and artifact.get("step_index") == step_index:
            best = artifact
            break
        if best is None:
            best = artifact
    return _first_line(best.get("summary")) if best else ""


def extract_memory_slots(
    existing: dict[str, Any] | None,
    state: dict[str, Any],
    *,
    turn: int,
    max_slots: int,
) -> dict[str, Any]:
    """Merge this turn's entities into the conversation slot map.

    Entities are taken from the arguments of successful tool calls (the values
    the user named or the agent resolved), keyed by argument name. This is fully
    generic — no app-specific slot names are hard-coded. Last-write-wins per
    slot, then the map is capped to the most recently touched ``max_slots``.
    """
    memory: dict[str, Any] = {k: dict(v) for k, v in (existing or {}).items() if isinstance(v, dict)}
    tool_calls = state.get("tool_calls") or []
    artifacts = state.get("artifacts") or []

    for call in tool_calls:
        if str(call.get("status") or "").lower() != "ok":
            continue
        args = _parse_args(call.get("args_preview"))
        if not args:
            continue
        finding = _finding_for(call, artifacts)
        for key, raw_value in args.items():
            slot_key = str(key or "").strip()
            if not slot_key or len(slot_key) > _MAX_SLOT_KEY_CHARS:
                continue
            if slot_key.lower() in _FREEFORM_ARG_KEYS:
                continue
            value = _slot_value(raw_value)
            if not value:
                continue
            slot = {"value": value, "turn": int(turn), "tool": call.get("name")}
            if finding:
                slot["finding"] = finding
            memory[slot_key] = slot

    # Caller-supplied preferences (e.g. UI-selected context) win and are kept.
    runtime = state.get("runtime_context")
    caller_prefs = runtime.get("conversation_memory") if isinstance(runtime, dict) else None
    if isinstance(caller_prefs, dict):
        for key, raw_value in caller_prefs.items():
            value = _slot_value(raw_value)
            slot_key = str(key or "").strip()
            if value and slot_key and len(slot_key) <= _MAX_SLOT_KEY_CHARS:
                memory[slot_key] = {"value": value, "turn": int(turn), "tool": "caller"}

    if max_slots > 0 and len(memory) > max_slots:
        ranked = sorted(memory.items(), key=lambda kv: int(kv[1].get("turn", 0)), reverse=True)
        memory = dict(ranked[:max_slots])
    return memory


def render_memory(memory: dict[str, Any] | None) -> str:
    """Render the slot map as compact context lines (most recent first)."""
    if not isinstance(memory, dict) or not memory:
        return ""
    items = sorted(
        ((k, v) for k, v in memory.items() if isinstance(v, dict)),
        key=lambda kv: (-int(kv[1].get("turn", 0)), kv[0]),
    )
    lines: list[str] = []
    for key, slot in items:
        value = str(slot.get("value") or "").strip()
        if not value:
            continue
        finding = str(slot.get("finding") or "").strip()
        line = f"- {key} = {value}"
        if finding:
            line += f" ({finding})"
        lines.append(line)
    return "\n".join(lines)
