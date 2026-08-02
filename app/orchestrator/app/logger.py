"""Structured JSON logging via structlog to stdout."""

import logging
import sys

import structlog


def _redact_pii(logger, method_name, event_dict):
    """Scrub PII from string log values before writing them to stdout."""
    from app.core import pii

    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = pii.redact(value)
    return event_dict


def setup_logging(level: int = logging.INFO, service: str = "backend"):
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        _redact_pii,
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
