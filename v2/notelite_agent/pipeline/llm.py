"""Single LLM HTTP helper — non-streaming chat completions.

- **RunPod mode** (default ``LLM_ENDPOINT_MODE=runpod``): Mistral hosts (8001),
  primary → secondary failover; explicit ``stream: false``.
- **Legacy mode** (``LLM_ENDPOINT_MODE=legacy``): single ``CHAT_LLM_API_BASE``
  for local/dev (same URL shape as before).

Streaming chat uses ``services.inference_stream`` (Llama RunPod only).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from apis.schema import ChatCompletionModel
from core.config import (
    CHAT_LLM_API_BASE,
    LLM_API_KEY,
    LLM_ENDPOINT_MODE,
    get_sync_llm_bases,
    get_sync_llm_model_name,
    inference_completion_url,
)

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0


def llm_call(
    payload: ChatCompletionModel | dict[str, Any],
    *,
    base_url: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    params: dict | None = None,
) -> dict:
    """POST chat completions (non-stream). See module docstring for routing."""
    body_raw = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    body: dict[str, Any] = dict(body_raw)
    body["stream"] = False
    if not body.get("model"):
        body["model"] = get_sync_llm_model_name()

    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}

    # Explicit single endpoint (tests / overrides).
    if base_url is not None:
        url = f"{base_url.rstrip('/')}/chat/completions"
        resp = httpx.post(
            url,
            headers=headers,
            params=params,
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    if LLM_ENDPOINT_MODE == "legacy":
        url = f"{CHAT_LLM_API_BASE.rstrip('/')}/chat/completions"
        resp = httpx.post(
            url,
            headers=headers,
            params=params,
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    last_exc: BaseException | None = None
    for base in get_sync_llm_bases():
        url = inference_completion_url(base)
        try:
            resp = httpx.post(
                url,
                headers=headers,
                params=params,
                json=body,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            last_exc = e
            log.warning("llm_call.endpoint_failed", base=base, error=str(e))

    raise RuntimeError(
        "All Mistral RunPod endpoints failed for llm_call",
    ) from last_exc


if __name__ == "__main__":
    payload = {
        "model": "llama3.1",
        "messages": [
            {"role": "system", "content": "only rephrase the below text and give only the rephrased text and don't include any extra text."},
            {"role": "user", "content": "text: can you give me an example?"},
        ],
        "max_tokens": 1024,
        "temperature": 0.9,
    }
    resp = llm_call(payload)
    answer = resp["choices"][0]["message"]["content"]
    print(answer)
