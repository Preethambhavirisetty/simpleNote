"""Trace id propagation through Celery tasks and the agent middleware trust rule.

Async work must carry the originating request's trace id; inbound X-Trace-Id is
honored only from callers presenting the internal API key.
"""
from unittest.mock import MagicMock, patch

import pytest
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars

from app.logger import get_trace_id
from app.services.chat import conversation
from app.services.ingestion.workers.celery_app import celery_app
from app.services.ingestion.workers import ingestion_tasks


@pytest.fixture(autouse=True)
def clean_contextvars():
    clear_contextvars()
    yield
    clear_contextvars()


def test_persist_payload_carries_the_bound_trace_id():
    bind_contextvars(trace_id="trace-chat-1")
    with patch.object(celery_app, "send_task") as send_task:
        conversation.persist_assistant_message(
            request=MagicMock(user_id="u"),
            conversation_id="c",
            assistant_message_id="m",
            answer="a",
            model="model",
            usage={"total_tokens": 1},
            latency_ms=1,
            error_message=None,
            references=[],
            events=[],
        )
    payload = send_task.call_args.kwargs["args"][0]
    assert payload["trace_id"] == "trace-chat-1"


def test_persist_worker_binds_trace_from_payload():
    captured = {}

    class FakeClient:
        def update_message(self, **kwargs):
            captured["trace_id"] = get_trace_id()

    with patch(
        "app.shared.backend_conversation_client.BackendConversationClient", FakeClient
    ):
        ingestion_tasks.persist_message.apply(
            args=[{
                "user_id": "u", "conversation_id": "c", "message_id": "m",
                "trace_id": "trace-chat-2",
            }]
        ).get()

    assert captured["trace_id"] == "trace-chat-2"


def test_persist_worker_generates_a_trace_id_when_none_supplied():
    captured = {}

    class FakeClient:
        def update_message(self, **kwargs):
            captured["trace_id"] = get_trace_id()

    with patch(
        "app.shared.backend_conversation_client.BackendConversationClient", FakeClient
    ):
        ingestion_tasks.persist_message.apply(
            args=[{"user_id": "u", "conversation_id": "c", "message_id": "m"}]
        ).get()

    assert captured["trace_id"]  # fresh uuid, never empty


def test_ingest_worker_binds_trace_and_hides_it_from_the_orchestrator():
    captured = {}

    def fake_run(data=None, **kwargs):
        captured["trace_id"] = get_trace_id()
        captured["kwargs"] = kwargs
        captured["data"] = data
        return {"status": "processed"}

    orchestrator = MagicMock()
    orchestrator.return_value.run.side_effect = fake_run
    with patch.object(ingestion_tasks, "IngestionOrchestrator", orchestrator), \
         patch.object(ingestion_tasks, "init_llama_index_settings"):
        # kwargs form — how the backend's _dispatch_ingest enqueues.
        ingestion_tasks.ingest_in_background.apply(
            kwargs={"action": "upsert", "trace_id": "trace-note-1", "note_id": "n"}
        ).get()

    assert captured["trace_id"] == "trace-note-1"
    assert "trace_id" not in captured["kwargs"]

    with patch.object(ingestion_tasks, "IngestionOrchestrator", orchestrator), \
         patch.object(ingestion_tasks, "init_llama_index_settings"):
        # dict form — how the agent's queued route enqueues.
        ingestion_tasks.ingest_in_background.apply(
            args=[{"action": "upsert", "trace_id": "trace-note-2", "note_id": "n"}]
        ).get()

    assert captured["trace_id"] == "trace-note-2"
    assert "trace_id" not in captured["data"]


def test_worker_binding_clears_leftover_context_between_tasks():
    bind_contextvars(trace_id="stale-previous-task", user_id="stale-user")

    ingestion_tasks._bind_task_trace("trace-fresh")

    assert get_trace_id() == "trace-fresh"
    assert "user_id" not in get_contextvars()


class TestAgentMiddlewareTraceTrust:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient

        from app.main import app

        return TestClient(app)

    def test_unauthenticated_trace_header_is_ignored(self, client):
        response = client.get("/health", headers={"X-Trace-Id": "spoofed-trace"})
        assert response.headers["X-Trace-Id"] != "spoofed-trace"

    def test_internal_caller_trace_header_is_reused(self, client):
        with patch("app.main.AGENT_API_KEY", "test-key"):
            response = client.get(
                "/health",
                headers={"X-Trace-Id": "trace-internal", "X-API-Key": "test-key"},
            )
        assert response.headers["X-Trace-Id"] == "trace-internal"
