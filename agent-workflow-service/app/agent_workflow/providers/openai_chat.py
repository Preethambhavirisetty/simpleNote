from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.agent_workflow.config import AgentConfig
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
            timeout_seconds=config.policy.llm_timeout_seconds,
            temperature=llm.temperature,
            top_p=llm.top_p,
            top_k=llm.top_k,
            seed=llm.seed,
            default_max_tokens=llm.default_max_tokens,
        )

    def complete(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> str:
        body = self._request_body(messages, max_tokens=max_tokens, stream=False)
        data = with_transient_retries(lambda: self._post_json(body))
        return self._extract_message_content(data)

    def stream(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> Iterator[str]:
        body = self._request_body(messages, max_tokens=max_tokens, stream=True)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            with client.stream("POST", self._chat_completions_url(), headers=self._headers(), json=body) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line.removeprefix("data:").strip()
                    if raw == "[DONE]":
                        break
                    data = json.loads(raw)
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
        response = httpx.post(
            self._chat_completions_url(),
            headers=self._headers(),
            json={k: v for k, v in body.items() if v is not None},
            timeout=self.timeout_seconds,
        )
        if response.is_error:
            detail = response.text.strip()
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    err = payload.get("error")
                    if isinstance(err, str) and err:
                        detail = err
                    elif isinstance(err, dict) and err.get("message"):
                        detail = str(err["message"])
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(
                f"LLM request failed ({response.status_code}): {detail or response.reason_phrase}"
            ) from None
        return response.json()

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
