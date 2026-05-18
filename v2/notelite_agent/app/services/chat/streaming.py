from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import (
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_MODEL,
)
from app.services.chat.backend_conversation_client import BackendConversationClient
from app.services.chat.schema import ChatRequest
from app.services.ingestion.workers.celery_app import CONVERSATION_TASK, celery_app
from app.shared.utils import count_tokens


log = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 16
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TIMEOUT = 300.0

SYSTEM_PROMPT = (
    "You are Notelite, a helpful personal notes assistant. "
    "Answer clearly and conversationally. If previous messages are included, "
    "use them only as conversation context. Do not reveal secrets or API keys; "
    "if credentials appear in context, confirm their presence and mask values."
)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class StreamingService:
    def __init__(
        self,
        conversation_client: BackendConversationClient | None = None,
        *,
        model: str = LLM_MODEL,
    ):
        self.conversation_client = conversation_client or BackendConversationClient()
        self.model = model

    def stream(self, request: ChatRequest) -> StreamingResponse:
        query = request.query.strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query cannot be empty.")

        started_at = time.perf_counter()
        events: list[str] = ["chat stream started"]
        latencies_ms: dict[str, int] = {}

        try:
            conversation_id, user_message_id, assistant_message_id = self._init_conversation(
                request,
                query,
                events,
                latencies_ms,
            )
            history = self._load_history(
                request.user_id,
                conversation_id,
                {user_message_id, assistant_message_id},
                events,
                latencies_ms,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        prompt_started_at = time.perf_counter()
        messages = self._build_messages(query, history)
        prompt_tokens_estimate = self._estimate_prompt_tokens(messages)
        latencies_ms["prompt_ms"] = self._elapsed_ms(prompt_started_at)
        events.append(f"prompt built prompt_tokens_estimate={prompt_tokens_estimate}")

        def event_stream() -> Iterator[str]:
            yield _sse("meta", {
                "conversation_id": conversation_id,
                "message_id": assistant_message_id,
                "user_message_id": user_message_id,
                "model": self.model,
                "prompt_tokens_estimate": prompt_tokens_estimate,
            })

            answer_parts: list[str] = []
            error_message: str | None = None
            usage: dict[str, int] = {
                "prompt_tokens": prompt_tokens_estimate,
                "completion_tokens": 0,
                "total_tokens": prompt_tokens_estimate,
            }
            model_reported_usage = False
            inference_started_at = time.perf_counter()
            first_token_ms: int | None = None
            events.append("llm stream started")

            try:
                for item in self.stream_single_base(messages):
                    item_type = item.get("type")
                    if item_type == "content_delta":
                        content = item.get("content") or ""
                        if not content:
                            continue
                        if first_token_ms is None:
                            first_token_ms = self._elapsed_ms(inference_started_at)
                            latencies_ms["first_token_ms"] = first_token_ms
                            events.append(f"llm first_token latency_ms={first_token_ms}")
                        answer_parts.append(content)
                        yield _sse("delta", {"content": content})
                    elif item_type == "usage":
                        model_reported_usage = True
                        usage.update({k: v for k, v in (item.get("usage") or {}).items() if v is not None})
                    elif item_type == "error":
                        error_message = item.get("message") or "Inference service error"
                        events.append("llm stream error")
                        yield _sse("error", {"message": error_message})
                        break
            except httpx.HTTPError as exc:
                error_message = str(exc)
                events.append("llm http error")
                log.warning("chat stream HTTP error", exc_info=True)
                yield _sse("error", {"message": error_message})
            except Exception:
                error_message = "Inference service error"
                events.append("llm stream exception")
                log.warning("chat stream failed", exc_info=True)
                yield _sse("error", {"message": error_message})

            answer = "".join(answer_parts)
            latencies_ms["inference_ms"] = self._elapsed_ms(inference_started_at)
            latencies_ms["total_ms"] = self._elapsed_ms(started_at)
            events.append("llm.stream.completed" if not error_message else "llm.stream.failed")

            if not usage.get("completion_tokens"):
                usage["completion_tokens"] = count_tokens(answer) if answer else 0
            if not model_reported_usage or not usage.get("total_tokens"):
                usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)

            self._persist_assistant_message(
                request=request,
                conversation_id=conversation_id,
                assistant_message_id=assistant_message_id,
                answer=answer,
                usage=usage,
                latency_ms=latencies_ms["total_ms"],
                error_message=error_message,
                events=events,
            )

            yield _sse("done", {
                "conversation_id": conversation_id,
                "message_id": assistant_message_id,
                "latency_ms": latencies_ms["total_ms"],
                "latencies_ms": latencies_ms,
                "usage": usage,
                "events": events,
                "has_error": error_message is not None,
            })

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    def stream_single_base(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Iterator[dict[str, Any]]:
        body = {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST",
                self._chat_completions_url(),
                headers=self._headers(),
                json=body,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="ignore")
                    if not line.startswith("data:"):
                        continue

                    raw = line.removeprefix("data:").strip()
                    if raw == "[DONE]":
                        break

                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        log.debug("Skipping malformed stream line", extra={"line": raw[:200]})
                        continue

                    if data.get("error"):
                        yield {"type": "error", "message": str(data["error"])}
                        break

                    usage = data.get("usage")
                    if usage:
                        yield {"type": "usage", "usage": usage}

                    choices = data.get("choices") or []
                    if not choices:
                        continue

                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield {"type": "content_delta", "content": content}

    def _init_conversation(
        self,
        request: ChatRequest,
        query: str,
        events: list[str],
        latencies_ms: dict[str, int],
    ) -> tuple[str, str, str]:
        started_at = time.perf_counter()
        conversation_id = request.conversation_id
        if not conversation_id:
            conversation = self.conversation_client.create_conversation(
                request.user_id,
                title=request.conversation_title or query[:100],
            )
            conversation_id = conversation["id"]
            events.append("conversation.created")
        else:
            events.append("conversation.reused")

        user_message = self.conversation_client.create_message(
            request.user_id,
            conversation_id,
            role="user",
            content=query,
        )
        assistant_message = self.conversation_client.create_message(
            request.user_id,
            conversation_id,
            role="assistant",
            content="",
            status="partial",
            model_used=self.model,
        )
        events.append("messages.created")
        events.extend(self.conversation_client.drain_events())
        latencies_ms["conversation_ms"] = self._elapsed_ms(started_at)
        return conversation_id, user_message["id"], assistant_message["id"]

    def _load_history(
        self,
        user_id: str,
        conversation_id: str,
        exclude_message_ids: set[str],
        events: list[str],
        latencies_ms: dict[str, int],
    ) -> list[dict[str, str]]:
        started_at = time.perf_counter()
        history: list[dict[str, str]] = []
        for message in self.conversation_client.get_messages(user_id, conversation_id):
            if message.get("id") in exclude_message_ids:
                continue
            if message.get("role") not in {"user", "assistant", "system"}:
                continue
            if message.get("role") == "assistant" and message.get("status") != "complete":
                continue
            content = (message.get("content") or "").strip()
            if content:
                history.append({"role": message["role"], "content": content})

        events.append(f"history.loaded count={len(history[-MAX_HISTORY_MESSAGES:])}")
        events.extend(self.conversation_client.drain_events())
        latencies_ms["history_ms"] = self._elapsed_ms(started_at)
        return history[-MAX_HISTORY_MESSAGES:]

    @staticmethod
    def _build_messages(query: str, history: Sequence[dict[str, str]]) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": query})
        return messages

    def _persist_assistant_message(
        self,
        *,
        request: ChatRequest,
        conversation_id: str,
        assistant_message_id: str,
        answer: str,
        usage: dict[str, int],
        latency_ms: int,
        error_message: str | None,
        events: list[str],
    ) -> None:
        payload = {
            "user_id": request.user_id,
            "conversation_id": conversation_id,
            "message_id": assistant_message_id,
            "content": answer,
            "status": "error" if error_message else "complete",
            "model_used": self.model,
            "latency_ms": latency_ms,
            "tokens_used": usage.get("total_tokens"),
            "sources_used": [],
            "error_message": error_message,
        }
        try:
            celery_app.send_task(CONVERSATION_TASK, args=[payload])
            events.append("message.persist_queued")
        except Exception:
            events.append("message.persist_failed")
            log.warning("failed to queue assistant message persistence", exc_info=True)

    @staticmethod
    def _estimate_prompt_tokens(messages: Sequence[dict[str, str]]) -> int:
        # Chat templates vary by runtime; this is a close operational estimate.
        return sum(count_tokens(message.get("content", "")) + 4 for message in messages)

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return int((time.perf_counter() - started_at) * 1000)

    @staticmethod
    def _chat_completions_url() -> str:
        return f"{LLM_API_BASE.rstrip('/')}/chat/completions"

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
