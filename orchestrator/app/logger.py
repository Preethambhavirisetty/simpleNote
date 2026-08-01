"""Structured JSON logging via structlog.

All output goes through structlog → stdout (always).
When LOKI_URL is set, a background thread also pushes log entries to
Loki so they appear in Grafana dashboards.  If Loki is unreachable the
entries are silently dropped — stdout remains the source of truth.

The Loki pusher uses only stdlib (urllib) so it can never crash the app
due to a missing third-party dependency.
"""

import json
import logging
import os
import queue
import sys
import threading
import time as _time
import urllib.request

import structlog

_loki_queue: queue.Queue | None = None


def _loki_enqueue(logger, method_name, event_dict):
    """Structlog processor: copy the event dict onto the Loki queue."""
    if _loki_queue is not None:
        try:
            _loki_queue.put_nowait(dict(event_dict))
        except queue.Full:
            pass
    return event_dict


def _start_loki_pusher(loki_url: str, service: str):
    """Spawn a daemon thread that flushes queued log entries to Loki."""
    global _loki_queue
    _loki_queue = queue.Queue(maxsize=1_000)
    push_url = f"{loki_url.rstrip('/')}/loki/api/v1/push"

    def _worker():
        while True:
            batch: list[dict] = []
            try:
                batch.append(_loki_queue.get(timeout=2.0))
                while len(batch) < 200:
                    try:
                        batch.append(_loki_queue.get_nowait())
                    except queue.Empty:
                        break
            except queue.Empty:
                continue

            now_ns = str(int(_time.time() * 1e9))
            values = []
            for entry in batch:
                entry.pop("timestamp", None)
                line = json.dumps(entry, default=str)
                values.append([now_ns, line])

            payload = json.dumps({
                "streams": [{
                    "stream": {"service": service},
                    "values": values,
                }]
            }).encode()

            req = urllib.request.Request(
                push_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True, name="loki-pusher")
    t.start()


def _redact_pii(logger, method_name, event_dict):
    """Scrub PII from string log values so it never reaches stdout or Loki."""
    from app.core import pii

    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = pii.redact(value)
    return event_dict


def setup_logging(level: int = logging.INFO, service: str = "backend"):
    loki_url = os.getenv("LOKI_URL")
    if loki_url:
        _start_loki_pusher(loki_url, service)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        _redact_pii,
        _loki_enqueue,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


logger = structlog.get_logger()


def get_trace_id() -> str | None:
    """Return the current request's trace id bound in structlog contextvars, if any."""
    return structlog.contextvars.get_contextvars().get("trace_id")
