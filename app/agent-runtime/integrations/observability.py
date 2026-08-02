"""Structured run logging into the agentlog service (../../observability).

Three properties this must have, in order of importance:

1. It never breaks a run. If the SDK is not installed or the collector is
   down, every call here becomes a no-op. Observability that can take down the
   thing it observes is worse than none.
2. Steps do not have to be handed a logger. The run lives in a context
   variable, so any code in the call stack can reach it without a signature
   change - logging is cross-cutting, and threading a logger through every
   step would bury the actual arguments.
3. The two kinds of output stay distinct, as the service intends: `log` for
   the readable stream, `track` for values worth querying and charting later.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from config import AGENTLOG_ENABLED, AGENTLOG_ENDPOINT

_log = logging.getLogger(__name__)

try:
    import agentlog

    _SDK_AVAILABLE = True
except ImportError:  # the SDK lives in the observability app; optional here
    agentlog = None
    _SDK_AVAILABLE = False

_current: ContextVar[Any] = ContextVar("agentlog_run", default=None)
_configured = False


class _NullRun:
    """Stands in for a Run when logging is off, so callers need no branches."""

    def log(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def debug(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def info(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def warn(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def error(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def track(self, **values: Any) -> None:
        return None

    @contextmanager
    def timed(self, phase: str, message: str, **track: Any):
        yield _NullTimed()

    def finish(self, *args: Any, **kwargs: Any) -> None:
        return None


class _NullTimed:
    def track(self, **values: Any) -> None:
        return None


NULL_RUN = _NullRun()


def available() -> bool:
    return _SDK_AVAILABLE and AGENTLOG_ENABLED


def current() -> Any:
    """The run for the request in flight, or a no-op stand-in."""
    return _current.get() or NULL_RUN


@contextmanager
def run_logger(question: str, conversation_id: str | None, **metadata: Any):
    """Open a logged run for one request and close it however it ends."""
    if not available():
        yield NULL_RUN
        return

    global _configured
    if not _configured:
        agentlog.configure(AGENTLOG_ENDPOINT)
        _configured = True

    try:
        run = agentlog.start(
            question=question, conversation_id=conversation_id, metadata=metadata or None
        )
    except Exception:  # the collector being down must not fail the request
        _log.warning("agentlog unavailable; continuing without run logging", exc_info=True)
        yield NULL_RUN
        return

    token = _current.set(run)
    try:
        yield run
    except Exception as exc:
        _safely(run.error, "run failed: %s", exc, phase="run")
        _safely(run.finish, status="error", error=str(exc))
        raise
    finally:
        _current.reset(token)


def finish(answer: str | None, status: str = "ok", **track: Any) -> None:
    run = current()
    if track:
        _safely(run.track, **track)
    _safely(run.finish, final_answer=answer, status=status)


def _safely(call, *args: Any, **kwargs: Any) -> None:
    try:
        call(*args, **kwargs)
    except Exception:  # never let a logging failure surface to the caller
        _log.debug("agentlog call failed", exc_info=True)


# ── convenience wrappers, so call sites read as one line ───────────────────

def log(level: str, message: str, *args: Any, **kwargs: Any) -> None:
    """Log at a level chosen at runtime (a step is ok / paused / failed)."""
    _safely(current().log, level, message, *args, **kwargs)


def debug(message: str, *args: Any, **kwargs: Any) -> None:
    _safely(current().debug, message, *args, **kwargs)


def info(message: str, *args: Any, **kwargs: Any) -> None:
    _safely(current().info, message, *args, **kwargs)


def warn(message: str, *args: Any, **kwargs: Any) -> None:
    _safely(current().warn, message, *args, **kwargs)


def error(message: str, *args: Any, **kwargs: Any) -> None:
    _safely(current().error, message, *args, **kwargs)


def track(**values: Any) -> None:
    _safely(current().track, **values)


@contextmanager
def timed(phase: str, message: str, **track_values: Any):
    run = current()
    try:
        with run.timed(phase, message, **track_values) as handle:
            yield handle
    except Exception:
        # A broken timer must not swallow or mask the work inside the block.
        yield _NullTimed()


def preview(value: Any, limit: int = 400) -> Any:
    """Trim a payload for the log stream without hiding its shape.

    Whole retrieval results are too big to store per line, but a count plus the
    first entries is usually what you actually want when reading a trace.
    """
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}..."
    if isinstance(value, list):
        return {
            "count": len(value),
            "sample": [preview(item, limit) for item in value[:3]],
        }
    if isinstance(value, dict):
        return {key: preview(item, limit) for key, item in list(value.items())[:12]}
    return value
