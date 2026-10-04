import asyncio
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import chat
from app.exceptions.base import AppException
from app.schema.base import ErrorCode


def test_stream_limiter_enforces_per_user_cap():
    limiter = chat._ActiveStreamLimiter(max_per_user=2, max_global=10)
    leases = [limiter.acquire("user-1") for _ in range(2)]

    with pytest.raises(AppException) as exc:
        limiter.acquire("user-1")

    assert exc.value.status_code == 429
    assert exc.value.error_code == ErrorCode.RATE_LIMITED

    for lease in leases:
        lease.release()


def test_stream_limiter_enforces_global_cap():
    limiter = chat._ActiveStreamLimiter(max_per_user=2, max_global=2)
    leases = [limiter.acquire("user-1"), limiter.acquire("user-2")]

    with pytest.raises(AppException) as exc:
        limiter.acquire("user-3")

    assert exc.value.status_code == 429
    assert exc.value.error_code == ErrorCode.RATE_LIMITED

    for lease in leases:
        lease.release()


def test_stream_lease_is_released_when_iterator_closes(monkeypatch):
    class FakeResponse:
        is_error = False
        headers = {"content-type": "text/event-stream"}

        async def aiter_raw(self):
            yield b"data: done\n\n"

        async def aclose(self):
            pass

    class FakeClient:
        def __init__(self, timeout):
            assert timeout.read == 300.0

        def build_request(self, *args, **kwargs):
            return object()

        async def send(self, request, stream):
            return FakeResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(chat.httpx, "AsyncClient", FakeClient)
    limiter = chat._ActiveStreamLimiter(max_per_user=1, max_global=1)
    lease = limiter.acquire("user-1")

    async def consume_stream():
        response = await chat._proxy_agent_stream({}, lease)
        return [chunk async for chunk in response.body_iterator]

    assert asyncio.run(consume_stream()) == [b"data: done\n\n"]
    replacement = limiter.acquire("user-2")
    replacement.release()


def test_limited_proxy_releases_lease_on_upstream_failure(monkeypatch):
    limiter = chat._ActiveStreamLimiter(max_per_user=1, max_global=1)

    async def fail(_payload, _lease):
        raise AppException("Unavailable", 503, ErrorCode.AGENT_UNAVAILABLE)

    monkeypatch.setattr(chat, "_stream_limiter", limiter)
    monkeypatch.setattr(chat, "_proxy_agent_stream", fail)
    payload = chat.ChatStreamRequest(query="hello")
    user = SimpleNamespace(id="user-1", role=["standard_user"])

    with pytest.raises(AppException):
        asyncio.run(chat._limited_proxy(payload, user))

    replacement = limiter.acquire("user-2")
    replacement.release()
