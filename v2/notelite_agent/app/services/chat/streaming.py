from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import LLM_REASONER_MODEL
from app.services.chat import conversation, llm_client, prompt, retriever
from app.services.chat.schema import ChatRequest
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.backend_conversation_client import BackendConversationClient
from app.shared.utils import count_tokens


log = logging.getLogger(__name__)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


class StreamingService:
    """Orchestrates a single streaming chat turn.

    Delegates each concern to a focused module:
        conversation  — lifecycle (init, history, persist)
        retriever     — two-stage RAG (summaries → chunks → rerank)
        prompt        — message assembly and token estimation
        llm_client    — HTTP SSE streaming to the remote LLM
    """

    def __init__(
        self,
        conversation_client: BackendConversationClient | None = None,
        *,
        model: str = LLM_REASONER_MODEL,
    ):
        self.conversation_client = conversation_client or BackendConversationClient()
        self.model = model

    def stream(
        self,
        request: ChatRequest,
        *,
        vector_store: QdrantVectorStore | None = None,
    ) -> StreamingResponse:
        query = request.query.strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query cannot be empty.")

        started_at = time.perf_counter()
        events: list[str] = ["chat stream started"]
        latencies_ms: dict[str, int] = {}

        # ── Conversation setup ────────────────────────────────────────────────
        try:
            conversation_id, user_message_id, assistant_message_id = (
                conversation.init_conversation(
                    self.conversation_client, request, query, self.model,
                    events, latencies_ms,
                )
            )
            history = conversation.load_history(
                self.conversation_client,
                request.user_id,
                conversation_id,
                {user_message_id, assistant_message_id},
                events,
                latencies_ms,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # ── Retrieval ─────────────────────────────────────────────────────────
        context_texts: list[str] = []
        source_ids: list[str] = []
        if vector_store is not None:
            retrieval_started = time.perf_counter()
            try:
                context_texts, source_ids = retriever.retrieve_context(
                    vector_store, query, request.user_id, request.k, request.role,
                )
                latencies_ms["retrieval_ms"] = _elapsed_ms(retrieval_started)
                events.append(f"retrieval.completed chunks={len(context_texts)}")
            except Exception:
                latencies_ms["retrieval_ms"] = _elapsed_ms(retrieval_started)
                events.append("retrieval.failed")
                log.warning("context retrieval failed", exc_info=True)

        # ── Prompt assembly ───────────────────────────────────────────────────
        prompt_started = time.perf_counter()
        messages = prompt.build_messages(query, history, context_texts)
        prompt_tokens_estimate = prompt.estimate_prompt_tokens(messages)
        latencies_ms["prompt_ms"] = _elapsed_ms(prompt_started)
        events.append(f"prompt built prompt_tokens_estimate={prompt_tokens_estimate}")

        # ── Streaming generator ───────────────────────────────────────────────
        def event_stream() -> Iterator[str]:
            yield _sse("meta", {
                "conversation_id": conversation_id,
                "message_id": assistant_message_id,
                "user_message_id": user_message_id,
                "model": self.model,
                "prompt_tokens_estimate": prompt_tokens_estimate,
                "context_chunks": len(context_texts),
            })

            answer_parts: list[str] = []
            error_message: str | None = None
            usage: dict[str, int] = {
                "prompt_tokens": prompt_tokens_estimate,
                "completion_tokens": 0,
                "total_tokens": prompt_tokens_estimate,
            }
            model_reported_usage = False
            inference_started = time.perf_counter()
            first_token_ms: int | None = None
            events.append("llm stream started")

            try:
                for item in llm_client.stream_llm(messages, model=self.model):
                    item_type = item.get("type")
                    if item_type == "content_delta":
                        content = item.get("content") or ""
                        if not content:
                            continue
                        if first_token_ms is None:
                            first_token_ms = _elapsed_ms(inference_started)
                            latencies_ms["first_token_ms"] = first_token_ms
                            events.append(f"llm first_token latency_ms={first_token_ms}")
                        answer_parts.append(content)
                        yield _sse("delta", {"content": content})
                    elif item_type == "usage":
                        model_reported_usage = True
                        usage.update({
                            k: v for k, v in (item.get("usage") or {}).items()
                            if v is not None
                        })
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
            latencies_ms["inference_ms"] = _elapsed_ms(inference_started)
            latencies_ms["total_ms"] = _elapsed_ms(started_at)
            events.append("llm.stream.completed" if not error_message else "llm.stream.failed")

            if not usage.get("completion_tokens"):
                usage["completion_tokens"] = count_tokens(answer) if answer else 0
            if not model_reported_usage or not usage.get("total_tokens"):
                usage["total_tokens"] = (
                    usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                )

            conversation.persist_assistant_message(
                request=request,
                conversation_id=conversation_id,
                assistant_message_id=assistant_message_id,
                answer=answer,
                model=self.model,
                usage=usage,
                latency_ms=latencies_ms["total_ms"],
                error_message=error_message,
                source_ids=source_ids,
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
