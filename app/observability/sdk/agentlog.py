"""Drop-in logger for the agent app.

    import agentlog

    run = agentlog.start(question=q, conversation_id=cid)
    run.info("matched %d candidates", n, phase="resolve_playbook")
    run.debug("scoring", phase="resolve_playbook", data={"scores": scores})
    run.track(playbook="incident_triage", score=0.91)
    with run.timed("llm", "resolve operation") as t:
        ...
        t.track(model="sample-model", input_tokens=4210)
    run.error("tool timeout, retry 1/3", phase="tool")
    run.finish(final_answer=answer)

Design rules:
  * Never block or crash the agent. Delivery is best-effort on a daemon thread
    with a bounded queue; if the queue overflows we drop the oldest lines and
    say so rather than applying backpressure to real work.
  * `seq` is assigned here, under a lock, so ordering survives concurrency and
    out-of-order HTTP delivery.
  * `track()` takes any name. New names need no migration and no code change on
    the server -- they register themselves on first sight.
"""

from __future__ import annotations

import atexit
import inspect
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

DEFAULT_ENDPOINT = os.environ.get("AGENTLOG_ENDPOINT", "http://127.0.0.1:8000")
DEFAULT_QUEUE_MAX = 10_000
DEFAULT_BATCH = 100
DEFAULT_FLUSH_S = 2.0

_SENTINEL = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _caller(depth: int = 3) -> str | None:
    """'planner.py:142' for the frame that called into the logger."""
    try:
        frame = inspect.stack()[depth]
        return f"{os.path.basename(frame.filename)}:{frame.lineno}"
    except (IndexError, ValueError):
        return None


class _Transport:
    """Background sender. One thread, bounded queue, best-effort delivery."""

    def __init__(
        self,
        endpoint: str,
        queue_max: int = DEFAULT_QUEUE_MAX,
        batch_size: int = DEFAULT_BATCH,
        flush_interval: float = DEFAULT_FLUSH_S,
        timeout: float = 5.0,
        fallback_path: str | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.timeout = timeout
        self.fallback_path = fallback_path
        self.dropped = 0
        self._q: queue.Queue = queue.Queue(maxsize=queue_max)
        self._thread = threading.Thread(
            target=self._loop, name="agentlog-transport", daemon=True
        )
        self._thread.start()
        atexit.register(self.close)

    # -- public ---------------------------------------------------------
    def enqueue(self, run_key: str, line: dict) -> None:
        try:
            self._q.put_nowait((run_key, line))
        except queue.Full:
            # drop the oldest so the newest (usually the interesting one) lands
            try:
                self._q.get_nowait()
                self.dropped += 1
                self._q.put_nowait((run_key, line))
            except (queue.Empty, queue.Full):
                self.dropped += 1

    def post(self, path: str, payload: dict) -> dict | None:
        body = json.dumps(payload, default=str).encode()
        req = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._fallback({"path": path, "payload": payload, "error": str(exc)})
            return None

    def flush(self, block: bool = True) -> None:
        if block:
            self._q.join()

    def close(self) -> None:
        try:
            self._q.put_nowait((None, _SENTINEL))
        except queue.Full:
            pass
        self._thread.join(timeout=5.0)

    # -- internals ------------------------------------------------------
    def _loop(self) -> None:
        pending: dict[str, list[dict]] = {}
        counted = 0
        deadline = time.monotonic() + self.flush_interval

        while True:
            timeout = max(0.0, deadline - time.monotonic())
            try:
                run_key, line = self._q.get(timeout=timeout)
            except queue.Empty:
                self._send(pending)
                pending, counted = {}, 0
                deadline = time.monotonic() + self.flush_interval
                continue

            if line is _SENTINEL:
                self._q.task_done()
                self._send(pending)
                return

            pending.setdefault(run_key, []).append(line)
            counted += 1
            self._q.task_done()

            if counted >= self.batch_size or time.monotonic() >= deadline:
                self._send(pending)
                pending, counted = {}, 0
                deadline = time.monotonic() + self.flush_interval

    def _send(self, pending: dict[str, list[dict]]) -> None:
        for run_key, lines in pending.items():
            if lines:
                self.post(f"/api/v1/runs/{run_key}/logs", {"logs": lines})

    def _fallback(self, record: dict) -> None:
        """If the service is unreachable, keep the lines on disk."""
        if not self.fallback_path:
            return
        try:
            with open(self.fallback_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass


class Run:
    """A single question-to-answer run."""

    def __init__(
        self,
        transport: _Transport,
        run_key: str,
        conversation_id: str | None = None,
        default_phase: str | None = None,
    ) -> None:
        self.transport = transport
        self.run_key = run_key
        self.conversation_id = conversation_id
        self.default_phase = default_phase
        self._seq = 0
        self._lock = threading.Lock()

    # -- ordering -------------------------------------------------------
    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    # -- emitting -------------------------------------------------------
    def log(
        self,
        level: str,
        message: str,
        *args: Any,
        phase: str | None = None,
        data: dict | None = None,
        duration_ms: int | None = None,
        track: dict | None = None,
        source: str | None = None,
        _depth: int = 3,
    ) -> int:
        if args:
            try:
                message = message % args
            except (TypeError, ValueError):
                message = " ".join([message, *(str(a) for a in args)])

        seq = self._next_seq()
        self.transport.enqueue(
            self.run_key,
            {
                "seq": seq,
                "ts": _now_iso(),
                "level": level,
                "phase": phase or self.default_phase,
                "message": message,
                "source": source or _caller(_depth),
                "data": data,
                "duration_ms": duration_ms,
                "track": track or None,
            },
        )
        return seq

    def debug(self, message: str, *args: Any, **kw: Any) -> int:
        return self.log("DEBUG", message, *args, **kw)

    def info(self, message: str, *args: Any, **kw: Any) -> int:
        return self.log("INFO", message, *args, **kw)

    def warn(self, message: str, *args: Any, **kw: Any) -> int:
        return self.log("WARN", message, *args, **kw)

    def error(self, message: str, *args: Any, **kw: Any) -> int:
        return self.log("ERROR", message, *args, **kw)

    def track(
        self, _message: str | None = None, /, _phase: str | None = None, **values: Any
    ) -> int:
        """Record tracked values. Any name works; new ones self-register.

            run.track(playbook="incident_triage", score=0.91)
            run.track("chose operation", operation="k8s.rollout_undo")
            run.track(_phase="memory", memory_turns=3)
        """
        names = ", ".join(values)
        return self.log(
            "INFO",
            _message or f"tracked {names}",
            phase=_phase or self.default_phase,
            track=values,
            # [0]=_caller [1]=log [2]=track [3]=caller
            _depth=3,
        )

    @contextmanager
    def timed(self, phase: str, message: str, level: str = "INFO", **track: Any):
        """Time a block and log it once, on the way out.

            with run.timed("tool", "k8s.describe_pod") as t:
                result = call()
                t.track(tool_name="k8s.describe_pod", rows=len(result))
        """
        started = time.perf_counter()
        collected: dict[str, Any] = dict(track)
        holder = _Timed(collected)
        failed: BaseException | None = None
        try:
            yield holder
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            failed = exc
            raise
        finally:
            elapsed = int((time.perf_counter() - started) * 1000)
            if failed is not None:
                collected.setdefault("error_class", type(failed).__name__)
            self.log(
                "ERROR" if failed is not None else level,
                f"{message} failed: {failed}" if failed is not None else message,
                phase=phase,
                duration_ms=elapsed,
                track={f"{phase}_latency_ms": elapsed, **collected},
                # one deeper than track(): contextlib's __exit__ sits between
                # this generator frame and the caller's `with` statement
                _depth=4,
            )

    # -- lifecycle ------------------------------------------------------
    def finish(
        self,
        final_answer: str | None = None,
        status: str = "ok",
        error_message: str | None = None,
    ) -> None:
        self.transport.flush()
        if self.transport.dropped:
            self.transport.post(
                f"/api/v1/runs/{self.run_key}/logs",
                {
                    "logs": [
                        {
                            "seq": self._next_seq(),
                            "ts": _now_iso(),
                            "level": "WARN",
                            "phase": "agentlog",
                            "message": (
                                f"{self.transport.dropped} log lines dropped "
                                "(transport queue full)"
                            ),
                            "track": {"dropped_log_lines": self.transport.dropped},
                        }
                    ]
                },
            )
        self.transport.post(
            f"/api/v1/runs/{self.run_key}/finish",
            {
                "status": status,
                "final_answer": final_answer,
                "error_message": error_message,
                "ended_at": _now_iso(),
            },
        )

    def __enter__(self) -> Run:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.error("run failed: %s", exc, phase="agentlog")
            self.finish(status="error", error_message=f"{exc_type.__name__}: {exc}")
        else:
            self.finish()
        return False


class _Timed:
    def __init__(self, sink: dict[str, Any]) -> None:
        self._sink = sink

    def track(self, **values: Any) -> None:
        self._sink.update(values)


_transport: _Transport | None = None


def configure(endpoint: str | None = None, **kwargs: Any) -> _Transport:
    global _transport
    if _transport is not None:
        _transport.close()
    _transport = _Transport(endpoint or DEFAULT_ENDPOINT, **kwargs)
    return _transport


def _get_transport() -> _Transport:
    global _transport
    if _transport is None:
        _transport = _Transport(DEFAULT_ENDPOINT)
    return _transport


def start(
    question: str | None = None,
    conversation_id: str | None = None,
    run_key: str | None = None,
    metadata: dict | None = None,
    default_phase: str | None = None,
) -> Run:
    """Begin a run. Returns a Run you log against."""
    transport = _get_transport()
    key = run_key or uuid.uuid4().hex
    transport.post(
        "/api/v1/runs",
        {
            "run_key": key,
            "conversation_id": conversation_id,
            "question": question,
            "started_at": _now_iso(),
            "metadata": metadata,
        },
    )
    return Run(transport, key, conversation_id, default_phase)
