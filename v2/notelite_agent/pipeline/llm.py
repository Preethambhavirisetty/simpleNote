"""Single LLM HTTP helper used by every module in the project.

All callers below use ``llm_call`` directly, each caller handles errors and extracts content in its own context.
- chat-side (inference, rewriting, intent)
- ingestion-side(summarization, keyword dedup, question generation)

Sample request:
{
    "model": "llama3.1",
    "messages": [
        {"role": "system", "content": "only rephrase the below text and give only the rephrased text and don't include any extra text."},
        {"role": "user", "content": "text: can you give me an example?"},
    ],
    "max_tokens": 1024,
    "temperature": 0.9
}

Sample reponse:
{
    "id": "chatcmpl-69e1b3eb",
    "object": "chat.completion",
    "created": 1776399339,
    "model": "llama3.1",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Can you show me a specific instance of what you're asking about?"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 47,
        "completion_tokens": 14,
        "total_tokens": 61
    }
}
"""

import httpx

from core.config import CHAT_LLM_API_BASE, LLM_API_KEY
from apis.schema import ChatCompletionModel

_DEFAULT_TIMEOUT = 30.0


def llm_call(
    payload: ChatCompletionModel,
    *,
    base_url: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    params: dict | None = None,
) -> dict:
    """Send a chat completion request and return the parsed response JSON.

    ``payload`` may be a dict or a Pydantic model (serialised via
    ``model_dump()``).  ``base_url`` defaults to ``CHAT_LLM_API_BASE``.
    Raises on non-2xx responses so callers handle errors in context.
    """
    body = payload.model_dump() if hasattr(payload, "model_dump") else payload
    url = f"{base_url or CHAT_LLM_API_BASE}/chat/completions"

    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        params=params,
        json=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()

if __name__ == "__main__":
    payload = {
        "model": "llama3.1",
        "messages": [
            {"role": "system", "content": "only rephrase the below text and give only the rephrased text and don't include any extra text."},
            {"role": "user", "content": "text: can you give me an example?"},
        ],
        "max_tokens": 1024,
        "temperature": 0.9
    }
    resp = llm_call(payload)
    answer = resp["choices"][0]["message"]["content"]
    print(answer)