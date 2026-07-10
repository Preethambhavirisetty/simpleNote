"""Asynchronous, non-blocking Splunk HEC log sink for per-step workflow logs.

A single background daemon thread drains a bounded queue and ships batched
events to a Splunk HTTP Event Collector. The agent loop only ever enqueues
(never blocks): if the queue is full, events are dropped and counted rather
than back-pressuring the run. Disabled by default; enabled via env.

Env vars:
    SPLUNK_HEC_ENABLED                (default false)
    SPLUNK_HEC_URL                    e.g. https://splunk:8088/services/collector/event
    SPLUNK_HEC_TOKEN
    SPLUNK_HEC_INDEX                  (optional)
    SPLUNK_HEC_SOURCE                 (default agent-workflow)
    SPLUNK_HEC_SOURCETYPE             (default agent_workflow:step)
    SPLUNK_HEC_VERIFY_SSL             (default true)
    SPLUNK_HEC_BATCH_SIZE             (default 50)
    SPLUNK_HEC_FLUSH_INTERVAL_SECONDS (default 2.0)
    SPLUNK_HEC_QUEUE_MAXSIZE          (default 10000)
    SPLUNK_HEC_TIMEOUT_SECONDS        (default 10.0)
    SPLUNK_HEC_LOG_STATE              (default false — ship the full AgentState per step)
    SPLUNK_HEC_MAX_EVENT_CHARS        (default 200000 — cap for the per-step state blob)
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.agent_workflow.util.http import is_transient_http_error

log = logging.getLogger(__name__)


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip()) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(str(value).strip()) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


@dataclass
class SplunkHecConfig:
    """Runtime settings for the Splunk HEC sink."""
    enabled: bool = False
    url: str = ""
    token: str = ""
    index: str = ""
    source: str = "agent-workflow"
    sourcetype: str = "agent_workflow:step"
    verify_ssl: bool = True
    batch_size: int = 50
    flush_interval_seconds: float = 2.0
    queue_maxsize: int = 10000
    timeout_seconds: float = 10.0
    log_state: bool = False
    max_event_chars: int = 200000

    @classmethod
    def from_env(cls) -> "SplunkHecConfig":
        url = (os.getenv("SPLUNK_HEC_URL") or "").strip()
        token = (os.getenv("SPLUNK_HEC_TOKEN") or "").strip()
        enabled = _as_bool(os.getenv("SPLUNK_HEC_ENABLED"), False) and bool(url) and bool(token)
        return cls(
            enabled=enabled,
            url=url,
            token=token,
            index=(os.getenv("SPLUNK_HEC_INDEX") or "").strip(),
            source=(os.getenv("SPLUNK_HEC_SOURCE") or "agent-workflow").strip(),
            sourcetype=(os.getenv("SPLUNK_HEC_SOURCETYPE") or "agent_workflow:step").strip(),
            verify_ssl=_as_bool(os.getenv("SPLUNK_HEC_VERIFY_SSL"), True),
            batch_size=max(1, _as_int(os.getenv("SPLUNK_HEC_BATCH_SIZE"), 50)),
            flush_interval_seconds=max(0.1, _as_float(os.getenv("SPLUNK_HEC_FLUSH_INTERVAL_SECONDS"), 2.0)),
            queue_maxsize=max(1, _as_int(os.getenv("SPLUNK_HEC_QUEUE_MAXSIZE"), 10000)),
            timeout_seconds=max(1.0, _as_float(os.getenv("SPLUNK_HEC_TIMEOUT_SECONDS"), 10.0)),
            log_state=_as_bool(os.getenv("SPLUNK_HEC_LOG_STATE"), False),
            max_event_chars=max(1000, _as_int(os.getenv("SPLUNK_HEC_MAX_EVENT_CHARS"), 200000)),
        )


class SplunkHecSink:
    """Background batching sender for Splunk HEC. Enqueue is always non-blocking."""

    def __init__(self, config: SplunkHecConfig, *, client: Any = None, start_worker: bool = True):
        self.config = config
        self._queue: queue.Queue = queue.Queue(maxsize=config.queue_maxsize)
        self._client = client
        self._owns_client = client is None
        self._stop = threading.Event()
        self._dropped = 0
        self._sent = 0
        self._worker: threading.Thread | None = None
        if config.enabled and start_worker:
            self._worker = threading.Thread(target=self._run, name="splunk-hec", daemon=True)
            self._worker.start()

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def sent(self) -> int:
        return self._sent

    def emit(self, event: dict[str, Any], *, sourcetype: str | None = None, time_epoch: float | None = None) -> bool:
        """Enqueue one event non-blocking. Returns False if dropped (queue full or disabled)."""
        if not self.config.enabled:
            return False
        record: dict[str, Any] = {
            "time": time_epoch if time_epoch is not None else time.time(),
            "source": self.config.source,
            "sourcetype": sourcetype or self.config.sourcetype,
            "event": event,
        }
        if self.config.index:
            record["index"] = self.config.index
        try:
            self._queue.put_nowait(record)
            return True
        except queue.Full:
            self._dropped += 1
            return False

    # -- worker / sending -----------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            batch: list[dict[str, Any]] = []
            try:
                batch.append(self._queue.get(timeout=self.config.flush_interval_seconds))
            except queue.Empty:
                continue
            while len(batch) < self.config.batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            self._send_batch(batch)
        self.flush_now()  # drain anything left after a stop signal

    def flush_now(self) -> None:
        """Synchronously send everything currently queued (shutdown / tests)."""
        batch: list[dict[str, Any]] = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
            if len(batch) >= self.config.batch_size:
                self._send_batch(batch)
                batch = []
        if batch:
            self._send_batch(batch)

    def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = httpx.Client(timeout=self.config.timeout_seconds, verify=self.config.verify_ssl)
        return self._client

    def _send_batch(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        payload = "\n".join(self._serialize(record) for record in batch)
        headers = {"Authorization": f"Splunk {self.config.token}"}
        client = self._ensure_client()
        for attempt in range(3):
            try:
                response = client.post(self.config.url, content=payload, headers=headers)
                if response.status_code < 400:
                    self._sent += len(batch)
                    return
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    time.sleep(min(0.5 * (2 ** attempt), 5.0))
                    continue
                log.warning("Splunk HEC rejected %d event(s) (%s): %s", len(batch), response.status_code, response.text[:200])
                return
            except httpx.HTTPError as exc:  # noqa: BLE001
                if is_transient_http_error(exc) and attempt < 2:
                    time.sleep(min(0.5 * (2 ** attempt), 5.0))
                    continue
                log.warning("Splunk HEC send failed for %d event(s): %s", len(batch), exc)
                return
        log.warning("Splunk HEC gave up on %d event(s) after retries", len(batch))

    def _serialize(self, record: dict[str, Any]) -> str:
        try:
            return json.dumps(record, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            fallback = {k: v for k, v in record.items() if k != "event"}
            fallback["event"] = {"error": "unserializable event"}
            return json.dumps(fallback, default=str, ensure_ascii=False)

    def close(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=timeout)
        elif self._worker is None:
            self.flush_now()
        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass


# -- process-wide singleton --------------------------------------------------

_sink: SplunkHecSink | None = None
_sink_lock = threading.Lock()
_sink_built = False


def get_splunk_sink() -> SplunkHecSink | None:
    """Return the process-wide sink, or None when Splunk HEC logging is disabled."""
    global _sink, _sink_built
    if _sink_built:
        return _sink
    with _sink_lock:
        if _sink_built:
            return _sink
        config = SplunkHecConfig.from_env()
        _sink = SplunkHecSink(config) if config.enabled else None
        _sink_built = True
        if _sink is not None:
            log.info("Splunk HEC logging enabled -> %s (state=%s)", config.url, config.log_state)
    return _sink


def close_splunk_sink() -> None:
    """Flush and stop the sink during service shutdown."""
    global _sink, _sink_built
    with _sink_lock:
        if _sink is not None:
            _sink.close()
        _sink = None
        _sink_built = False


def reset_splunk_sink() -> None:
    """Test helper: clear the cached singleton so env can be re-read."""
    close_splunk_sink()


atexit.register(close_splunk_sink)


# -- record builders + convenience emitters ----------------------------------


def build_step_record(
    *,
    thread_id: str,
    session_id: str,
    node: str,
    update: dict[str, Any],
    state: dict[str, Any],
    log_state: bool,
    max_event_chars: int,
) -> dict[str, Any]:
    """Build a compact per-step log event from a node update + merged state."""
    iteration = state.get("iteration") or {}
    record: dict[str, Any] = {
        "kind": "workflow.step",
        "thread_id": thread_id,
        "session_id": session_id,
        "node": node,
        "phase": state.get("phase") or "",
        "steps": [str(entry.get("step")) for entry in (update.get("events") or []) if entry.get("step")],
        "artifact_count": len(state.get("artifacts") or []),
        "tool_call_count": len(state.get("tool_calls") or []),
        "fact_count": len(state.get("facts") or []),
        "executor_turns": iteration.get("executor_turns"),
        "review_cycles": iteration.get("review_cycles"),
        "explore_cycles": iteration.get("explore_cycles"),
        "no_progress_turns": iteration.get("no_progress_turns"),
        "error": state.get("error"),
    }
    if log_state:
        # Round-trip through JSON to guarantee a safe, serializable copy, and cap
        # the size so a huge state cannot exceed the HEC per-event limit.
        try:
            blob = json.dumps(state, default=str)
        except (TypeError, ValueError):
            blob = ""
        if blob and len(blob) <= max_event_chars:
            record["state"] = json.loads(blob)
        else:
            record["state_truncated"] = True
            record["state_chars"] = len(blob)
    return record


def log_workflow_step(*, thread_id: str, session_id: str, node: str, update: dict[str, Any], state: dict[str, Any]) -> None:
    """Emit one per-step log event to Splunk (no-op when disabled)."""
    sink = get_splunk_sink()
    if sink is None:
        return
    sink.emit(
        build_step_record(
            thread_id=thread_id,
            session_id=session_id,
            node=node,
            update=update,
            state=state,
            log_state=sink.config.log_state,
            max_event_chars=sink.config.max_event_chars,
        )
    )


def log_workflow_event(*, thread_id: str, session_id: str, kind: str, data: dict[str, Any] | None = None) -> None:
    """Emit a run-level log event (run.started, run.completed, run.fast_path, …)."""
    sink = get_splunk_sink()
    if sink is None:
        return
    event = {"kind": kind, "thread_id": thread_id, "session_id": session_id}
    if data:
        event.update(data)
    sink.emit(event)
