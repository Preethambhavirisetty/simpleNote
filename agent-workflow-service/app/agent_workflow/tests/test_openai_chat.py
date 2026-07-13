from __future__ import annotations

from app.agent_workflow.providers.openai_chat import normalize_inference_model


def test_normalize_inference_model_strips_provider_prefix():
    assert normalize_inference_model("the-inference/reasoner") == "reasoner"
    assert normalize_inference_model("reasoner") == "reasoner"


def test_seed_omitted_from_request_when_unset():
    # No seed configured -> the request must not carry one, so the backend
    # samples with a fresh RNG per request (no identical answers across runs).
    provider = OpenAiChatCompletionsProvider(base_url="http://llm.example/v1", api_key="", model="m")
    body = provider._request_body([{"role": "user", "content": "hi"}], max_tokens=64, stream=False)
    sent = {k: v for k, v in body.items() if v is not None}  # mirrors _post_json filter
    assert "seed" not in sent

    pinned = OpenAiChatCompletionsProvider(base_url="http://llm.example/v1", api_key="", model="m", seed=42)
    body = pinned._request_body([{"role": "user", "content": "hi"}], max_tokens=64, stream=False)
    assert body["seed"] == 42


def test_legacy_seed_sentinel_normalizes_to_none():
    from app.agent_workflow.config import parse_agent_config

    base = {
        "name": "s",
        "prompts_inline": {"planner": "p", "executor": "e", "reviewer": "r"},
        "llm": {"base_url": "http://llm.local/v1", "model": "m", "seed": 0xFFFFFFFF},
    }
    assert parse_agent_config(base).llm.seed is None
    base["llm"].pop("seed")
    assert parse_agent_config(base).llm.seed is None
    base["llm"]["seed"] = 42
    assert parse_agent_config(base).llm.seed == 42


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
