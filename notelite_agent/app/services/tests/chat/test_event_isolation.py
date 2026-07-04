"""Per-request event isolation for backend conversation clients.

Concurrent chat requests must never read or drain each other's event logs,
while still sharing one underlying HTTP connection pool.
"""
import httpx

from app.services.chat.streaming import StreamingService
from app.shared.api_client import APIClient
from app.shared.backend_conversation_client import BackendConversationClient


def test_events_are_isolated_between_client_instances():
    first = BackendConversationClient()
    second = BackendConversationClient()

    first.api_client.events.extend(["first.call.1", "first.call.2"])
    second.api_client.events.append("second.call.1")

    assert first.drain_events() == ["first.call.1", "first.call.2"]
    # Draining one instance must not touch the other's events.
    assert second.drain_events() == ["second.call.1"]
    assert first.drain_events() == []


def test_instances_share_one_http_connection_pool():
    first = BackendConversationClient()
    second = BackendConversationClient()

    assert first.api_client.client is second.api_client.client
    assert first.api_client.events is not second.api_client.events


def test_streaming_service_builds_a_client_per_stream():
    service = StreamingService()

    assert service._conversation_client() is not service._conversation_client()


def test_streaming_service_uses_injected_client_for_tests():
    injected = BackendConversationClient()
    service = StreamingService(conversation_client=injected)

    assert service._conversation_client() is injected


def test_api_client_context_manager_does_not_close_a_shared_pool():
    shared = httpx.Client(base_url="http://example.invalid")
    try:
        with APIClient("http://example.invalid", client=shared):
            pass
        assert not shared.is_closed

        with APIClient("http://example.invalid") as owned:
            owned_http = owned.client
        assert owned_http.is_closed
    finally:
        shared.close()
