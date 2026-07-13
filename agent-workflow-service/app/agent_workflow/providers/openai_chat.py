from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.telemetry import record_llm_usage
from app.agent_workflow.util.http import is_transient_http_error, raise_for_workflow_status
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
    """OpenAI-compatible chat completions provider."""
    base_url: str
    model: str
    api_key: str = ""
    send_auth_header: bool = True
    timeout_seconds: float = 120.0
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int = 40
    # None = omitted from the request body (the None-filter in _post_json/stream
    # drops it), so the backend uses a fresh RNG per request.
    seed: int | None = None
    default_max_tokens: int = 1024
    _client: httpx.Client | None = field(default=None, init=False, repr=False)
    _usage_totals: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, init=False, repr=False)
    _usage_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def from_agent_config(cls, config: AgentConfig) -> "OpenAiChatCompletionsProvider":
        """From agent config."""
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
        """Run one non-streaming LLM completion request."""
        body = self._request_body(messages, max_tokens=max_tokens, stream=False)
        data = with_transient_retries(lambda: self._post_json(body))
        self._record_usage(data.get("usage"))
        return self._extract_message_content(data)

    def complete_with_tools(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """One chat turn with the OpenAI native tools contract.

        Returns {"content": str, "tool_calls": [{"name", "arguments"}]}; callers
        validate arguments against the tool schema before executing.
        """
        body = self._request_body(messages, max_tokens=max_tokens, stream=False)
        if tools:
            body["tools"] = list(tools)
            body["tool_choice"] = "auto"
        data = with_transient_retries(lambda: self._post_json(body))
        self._record_usage(data.get("usage"))
        choices = data.get("choices") or []
        message = (choices[0] or {}).get("message") or {} if choices else {}
        tool_calls: list[dict[str, Any]] = []
        for call in message.get("tool_calls") or []:
            function = (call or {}).get("function") or {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            raw_arguments = function.get("arguments")
            if isinstance(raw_arguments, dict):
                arguments = raw_arguments
            elif isinstance(raw_arguments, str) and raw_arguments.strip():
                try:
                    parsed = json.loads(raw_arguments)
                    arguments = parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    # Schema validation downstream reports the missing fields.
                    arguments = {}
            else:
                arguments = {}
            tool_calls.append({"name": name, "arguments": arguments})
        return {"content": self._extract_message_content(data), "tool_calls": tool_calls}

    def stream(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> Iterator[str]:
        """Run one streaming LLM completion request."""
        body = self._request_body(messages, max_tokens=max_tokens, stream=True)
        max_attempts = 3
        for attempt in range(max_attempts):
            emitted = False
            try:
                for chunk in self._stream_once(body):
                    emitted = True
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001
                # Only retry before the first chunk reaches the caller; a retry
                # after that would duplicate already-yielded tokens.
                if emitted or not is_transient_http_error(exc) or attempt == max_attempts - 1:
                    raise
                retry_after = getattr(exc, "retry_after", None)
                if isinstance(retry_after, (int, float)) and retry_after >= 0:
                    time.sleep(retry_after)
                else:
                    time.sleep(0.2 * (2**attempt))

    def usage_totals(self) -> dict[str, int]:
        """Usage totals."""
        with self._usage_lock:
            return dict(self._usage_totals)

    def close(self) -> None:
        """Release any underlying network or storage resources."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _request_body(self, messages: Sequence[dict[str, Any]], *, max_tokens: int, stream: bool) -> dict[str, Any]:
        """Helper for request body."""
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
        """Send one upstream POST request and return the parsed response."""
        response = self._http_client().post(
            self._chat_completions_url(),
            headers=self._headers(),
            json={k: v for k, v in body.items() if v is not None},
        )
        raise_for_workflow_status(response, service="LLM")
        return response.json()

    def _stream_once(self, body: dict[str, Any]) -> Iterator[str]:
        """Helper for stream once."""
        with self._http_client().stream(
            "POST",
            self._chat_completions_url(),
            headers=self._headers(),
            json={k: v for k, v in body.items() if v is not None},
        ) as response:
            if response.is_error:
                # A streamed error body must be read before .text is accessible;
                # without this the status check raises ResponseNotRead instead of
                # a typed transient/permanent error and defeats the retry.
                response.read()
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
        """Helper for http client."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_seconds)
        return self._client

    def _record_usage(self, usage: Any) -> None:
        """Record usage into workflow state or telemetry."""
        if not isinstance(usage, dict):
            return
        # The provider is the only layer that sees exact usage from the
        # OpenAI-compatible response. The active debug trace supplies the label.
        record_llm_usage(usage)
        with self._usage_lock:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int):
                    self._usage_totals[key] = self._usage_totals.get(key, 0) + value

    def _headers(self) -> dict[str, str]:
        """Build request headers for the upstream service."""
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.send_auth_header:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _chat_completions_url(self) -> str:
        """Helper for chat completions url."""
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @staticmethod
    def _message_to_dict(message: dict[str, Any] | Any) -> dict[str, str]:
        """Helper for message to dict."""
        if not isinstance(message, dict):
            role = getattr(message, "role", "user")
            content = getattr(message, "content", "")
            return {"role": str(role), "content": str(content or "")}
        return {"role": str(message.get("role", "user")), "content": str(message.get("content", ""))}

    @staticmethod
    def _extract_message_content(data: dict[str, Any]) -> str:
        """Extract message content from a larger payload."""
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
