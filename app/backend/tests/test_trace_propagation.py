"""Trace id trust in the request middleware and propagation into Celery dispatch.

Public clients must not be able to inject trace ids; internal callers (valid
X-Internal-Key) keep theirs, and ingestion dispatches carry the bound trace id
so agent worker logs correlate with the originating request.
"""
from unittest.mock import patch

import pytest
from structlog.contextvars import bind_contextvars, clear_contextvars

INTERNAL_KEY = "test-internal-key"


@pytest.fixture(autouse=True)
def clean_contextvars():
    clear_contextvars()
    yield
    clear_contextvars()


class TestMiddlewareTraceTrust:
    def test_every_response_carries_a_trace_id(self, unauthed_client):
        response = unauthed_client.get("/api/health")
        assert response.headers.get("X-Trace-Id")

    def test_public_trace_header_is_ignored(self, unauthed_client):
        response = unauthed_client.get("/api/health", headers={"X-Trace-Id": "spoofed"})
        assert response.headers["X-Trace-Id"] != "spoofed"

    def test_trace_header_with_wrong_key_is_ignored(self, unauthed_client):
        with patch("app.main.AGENT_API_KEY", INTERNAL_KEY):
            response = unauthed_client.get(
                "/api/health",
                headers={"X-Trace-Id": "spoofed", "X-Internal-Key": "wrong"},
            )
        assert response.headers["X-Trace-Id"] != "spoofed"

    def test_internal_caller_trace_is_reused(self, unauthed_client):
        with patch("app.main.AGENT_API_KEY", INTERNAL_KEY):
            response = unauthed_client.get(
                "/api/health",
                headers={"X-Trace-Id": "trace-agent-1", "X-Internal-Key": INTERNAL_KEY},
            )
        assert response.headers["X-Trace-Id"] == "trace-agent-1"


class TestDispatchTracePropagation:
    def test_ingest_dispatch_includes_bound_trace_id(self):
        from app.services import notes

        bind_contextvars(trace_id="trace-note-save")
        with patch.object(notes, "celery_app") as celery_app:
            notes._dispatch_ingest({"note_id": "n"})

        kwargs = celery_app.send_task.call_args.kwargs["kwargs"]
        assert kwargs["trace_id"] == "trace-note-save"
        assert kwargs["action"] == "upsert"

    def test_delete_dispatch_includes_bound_trace_id(self):
        from app.services import notes

        bind_contextvars(trace_id="trace-note-delete")
        with patch.object(notes, "celery_app") as celery_app:
            notes._dispatch_delete({"note_id": "n"})

        kwargs = celery_app.send_task.call_args.kwargs["kwargs"]
        assert kwargs["trace_id"] == "trace-note-delete"
        assert kwargs["action"] == "delete"
