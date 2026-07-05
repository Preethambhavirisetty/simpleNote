from __future__ import annotations

from app.agent_workflow.providers.openai_chat import normalize_inference_model


def test_normalize_inference_model_strips_provider_prefix():
    assert normalize_inference_model("the-inference/reasoner") == "reasoner"
    assert normalize_inference_model("reasoner") == "reasoner"


import httpx
import pytest

from app.agent_workflow.providers.openai_chat import OpenAiChatCompletionsProvider
from app.agent_workflow.util.http import PermanentHTTPError


class _FakeClient:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = responses
        self.posts = 0
        self.closed = False

    def post(self, *args, **kwargs):
        self.posts += 1
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def _response(status: int, payload: dict | None = None, headers: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "http://llm.example/v1/chat/completions")
    return httpx.Response(status, json=payload or {}, headers=headers or {}, request=request)


def test_complete_retries_transient_http_statuses(monkeypatch):
    sleeps: list[float] = []
    fake = _FakeClient(
        [
            _response(503, {"error": {"message": "warming"}}),
            _response(429, {"error": "rate limited"}, {"Retry-After": "0"}),
            _response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    monkeypatch.setattr("app.agent_workflow.providers.openai_chat.httpx.Client", lambda **kwargs: fake)
    monkeypatch.setattr("app.agent_workflow.util.retry.time.sleep", sleeps.append)

    provider = OpenAiChatCompletionsProvider(base_url="http://llm.example/v1", model="test")

    assert provider.complete([{"role": "user", "content": "hi"}]) == "ok"
    assert fake.posts == 3
    assert sleeps == [0.2, 0.0]


def test_complete_does_not_retry_permanent_http_status(monkeypatch):
    fake = _FakeClient([_response(400, {"error": {"message": "bad request"}})])
    monkeypatch.setattr("app.agent_workflow.providers.openai_chat.httpx.Client", lambda **kwargs: fake)

    provider = OpenAiChatCompletionsProvider(base_url="http://llm.example/v1", model="test")

    with pytest.raises(PermanentHTTPError):
        provider.complete([{"role": "user", "content": "hi"}])
    assert fake.posts == 1


def test_openai_provider_reuses_and_closes_client(monkeypatch):
    fake = _FakeClient([
        _response(200, {"choices": [{"message": {"content": "one"}}]}),
        _response(200, {"choices": [{"message": {"content": "two"}}]}),
    ])
    created: list[_FakeClient] = []

    def make_client(**kwargs):
        created.append(fake)
        return fake

    monkeypatch.setattr("app.agent_workflow.providers.openai_chat.httpx.Client", make_client)
    provider = OpenAiChatCompletionsProvider(base_url="http://llm.example/v1", model="test")

    assert provider.complete([{"role": "user", "content": "hi"}]) == "one"
    assert provider.complete([{"role": "user", "content": "again"}]) == "two"
    assert len(created) == 1

    provider.close()
    assert fake.closed is True
