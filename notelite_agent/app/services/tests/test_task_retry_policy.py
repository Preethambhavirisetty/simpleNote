"""Celery retry coverage: transient failures must retry, not fail permanently.

Tasks run eagerly via .apply(); eager mode cannot re-execute, so the contract is
asserted on the task.retry() call the autoretry wrapper makes (patched to raise
celery's Retry, which .apply() reports as state RETRY).
"""
from unittest.mock import patch

import httpx
import pytest
from celery.exceptions import Retry

from app.services.ingestion.workers import ingestion_tasks


@pytest.fixture()
def persist_retry():
    with patch.object(ingestion_tasks.persist_message, "retry", side_effect=Retry("retrying")) as retry:
        yield retry


@pytest.fixture()
def ingest_retry():
    with patch.object(ingestion_tasks.ingest_in_background, "retry", side_effect=Retry("retrying")) as retry:
        yield retry


def persist_with_failing_client(exc):
    class FailingClient:
        def update_message(self, **kwargs):
            raise exc

    with patch(
        "app.shared.backend_conversation_client.BackendConversationClient", FailingClient
    ):
        return ingestion_tasks.persist_message.apply(
            args=[{"user_id": "u", "conversation_id": "c", "message_id": "m"}]
        )


def ingest_with_failing_run(exc):
    with patch.object(ingestion_tasks, "IngestionOrchestrator") as orchestrator, \
         patch.object(ingestion_tasks, "init_llama_index_settings"):
        orchestrator.return_value.run.side_effect = exc
        orchestrator._payload.return_value = {"action": "upsert", "note_id": "n"}
        return ingestion_tasks.ingest_in_background.apply(
            kwargs={"action": "upsert", "note_id": "n"}
        )


def test_persist_retries_on_backend_runtime_error(persist_retry):
    """_require_data surfaces backend 5xx/invalid responses as RuntimeError."""
    result = persist_with_failing_client(RuntimeError("Backend failed to update message."))
    assert result.status == "RETRY"
    assert persist_retry.called


def test_persist_retries_on_httpx_transport_error(persist_retry):
    result = persist_with_failing_client(httpx.ConnectError("connection refused"))
    assert result.status == "RETRY"
    assert persist_retry.called


def test_ingest_retries_on_httpx_error(ingest_retry):
    """Embedding/LLM calls raise httpx errors; the note must not be dropped."""
    result = ingest_with_failing_run(httpx.ReadTimeout("embedding timed out"))
    assert result.status == "RETRY"
    assert ingest_retry.called


def http_status_error(status_code):
    request = httpx.Request("POST", "http://example.invalid/embed")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("upstream failed", request=request, response=response)


def test_ingest_retries_on_http_5xx(ingest_retry):
    result = ingest_with_failing_run(http_status_error(503))
    assert result.status == "RETRY"
    assert ingest_retry.called


def test_ingest_does_not_retry_http_4xx(ingest_retry):
    result = ingest_with_failing_run(http_status_error(401))
    assert result.status == "FAILURE"
    assert not ingest_retry.called


def test_ingest_does_not_retry_validation_errors(ingest_retry):
    """Bad payloads are permanent failures, not retry storms."""
    result = ingest_with_failing_run(ValueError("Missing required fields"))
    assert result.status == "FAILURE"
    assert not ingest_retry.called
