"""Every remote HTTP surface must reuse one connection pool per module."""
import httpx

from app.core.embeddings import remote as embeddings_remote
from app.services.chat import llm_client, reranker
from app.shared import llm as shared_llm


def test_each_module_reuses_one_client():
    for module in (shared_llm, embeddings_remote, reranker, llm_client):
        first = module._http_client()
        assert module._http_client() is first
        assert isinstance(first, httpx.Client)


def test_embedding_instances_share_the_pool_across_timeouts():
    """The semantic chunker builds a service with a shorter timeout; timeouts
    are per-request, so it must not fork its own pool."""
    default_service = embeddings_remote.RemoteEmbeddingService()
    chunker_service = embeddings_remote.RemoteEmbeddingService(timeout=8.0)

    assert default_service.timeout != chunker_service.timeout
    assert embeddings_remote._http_client() is embeddings_remote._http_client()


def response_for(status_code):
    def handler(request):
        return httpx.Response(status_code, request=request, json={"error": "nope"})
    return handler


def test_api_client_does_not_raise_retry_for_4xx():
    from app.shared.api_client import APIClient

    client = httpx.Client(transport=httpx.MockTransport(response_for(401)), base_url="http://backend")
    api = APIClient("http://backend", client=client)

    assert api.post("/internal/messages", {}, timeout=1) is None
    assert any("status 401" in event for event in api.events)


def test_api_client_raises_retry_marker_for_5xx():
    from app.shared.api_client import APIClient
    from app.shared.http import TransientHTTPError

    client = httpx.Client(transport=httpx.MockTransport(response_for(503)), base_url="http://backend")
    api = APIClient("http://backend", client=client)

    try:
        api.post("/internal/messages", {}, timeout=1)
    except TransientHTTPError:
        pass
    else:
        raise AssertionError("5xx responses must be retryable")
