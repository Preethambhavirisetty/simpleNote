from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.util.http import raise_for_workflow_status
from app.agent_workflow.util.retry import with_transient_retries


def normalize_inference_model(model: str) -> str:
    """Map OpenAI-style model ids to inference-service use_case names."""
    value = str(model or "").strip()
    if not value:
        return value
    if "/" in value:
        value = value.rsplit("/", 1)[-1].strip()
    return value


@dataclass
class OpenAiChatCompletionsProvider:
    base_url: str
    model: str
    api_key: str = ""
    send_auth_header: bool = True
    timeout_seconds: float = 120.0
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int = 40
    seed: int = 0xFFFFFFFF
    default_max_tokens: int = 1024
    _client: httpx.Client | None = field(default=None, init=False, repr=False)
    _usage_totals: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, init=False, repr=False)
    _usage_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def from_agent_config(cls, config: AgentConfig) -> "OpenAiChatCompletionsProvider":
        llm = config.llm
        model = str(config.policy.model or llm.model or "").strip()
        base_url = str(llm.base_url or "").strip()
        if not base_url:
            raise RuntimeError("Missing LLM base_url. Set llm.base_url in agent config.")
        if not model:
            raise RuntimeError("Missing LLM model. Set policy.model or llm.model in agent config.")
        return cls(
            base_url=base_url,
            model=normalize_inference_model(model),
            api_key=llm.api_key,
            send_auth_header=llm.send_auth_header,
            timeout_seconds=max(0.1, config.policy.llm_timeout_seconds - 1.0),
            temperature=llm.temperature,
            top_p=llm.top_p,
            top_k=llm.top_k,
            seed=llm.seed,
            default_max_tokens=llm.default_max_tokens,
        )

    def complete(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> str:
        body = self._request_body(messages, max_tokens=max_tokens, stream=False)
        data = with_transient_retries(lambda: self._post_json(body))
        self._record_usage(data.get("usage"))
        return self._extract_message_content(data)

    def stream(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> Iterator[str]:
        body = self._request_body(messages, max_tokens=max_tokens, stream=True)
        for chunk in with_transient_retries(lambda: list(self._stream_once(body))):
            yield chunk

    def usage_totals(self) -> dict[str, int]:
        with self._usage_lock:
            return dict(self._usage_totals)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _request_body(self, messages: Sequence[dict[str, Any]], *, max_tokens: int, stream: bool) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [self._message_to_dict(m) for m in messages],
            "max_tokens": max_tokens or self.default_max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "seed": self.seed,
            "stream": stream,
            "stream_options": {"include_usage": True} if stream else None,
        }

    def _post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        response = self._http_client().post(
            self._chat_completions_url(),
            headers=self._headers(),
            json={k: v for k, v in body.items() if v is not None},
        )
        raise_for_workflow_status(response, service="LLM")
        return response.json()

    def _stream_once(self, body: dict[str, Any]) -> Iterator[str]:
        with self._http_client().stream(
            "POST",
            self._chat_completions_url(),
            headers=self._headers(),
            json={k: v for k, v in body.items() if v is not None},
        ) as response:
            raise_for_workflow_status(response, service="LLM")
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if raw == "[DONE]":
                    break
                data = json.loads(raw)
                self._record_usage(data.get("usage"))
                if "error" in data:
                    err = data["error"]
                    message = err if isinstance(err, str) else str(err.get("message", err))
                    raise RuntimeError(message)
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield str(content)

    def _http_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_seconds)
        return self._client

    def _record_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        with self._usage_lock:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int):
                    self._usage_totals[key] = self._usage_totals.get(key, 0) + value

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.send_auth_header:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @staticmethod
    def _message_to_dict(message: dict[str, Any] | Any) -> dict[str, str]:
        if not isinstance(message, dict):
            role = getattr(message, "role", "user")
            content = getattr(message, "content", "")
            return {"role": str(role), "content": str(content or "")}
        return {"role": str(message.get("role", "user")), "content": str(message.get("content", ""))}

    @staticmethod
    def _extract_message_content(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        first_choice = choices[0] or {}
        message = first_choice.get("message") or {}
        content = message.get("content")
        if content is not None:
            if isinstance(content, list):
                return "".join(str(part.get("text", part)) for part in content).strip()
            return str(content).strip()
        text = first_choice.get("text")
        return str(text).strip() if text is not None else ""
