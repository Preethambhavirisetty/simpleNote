from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from collections.abc import Iterator
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import ACTIVE_CHAT_SYSTEM_VERSION, LLM_REASONER_MODEL
from app.core.feature_flags import is_enabled
from app.logger import logger
from app.services.chat import conversation, llm_client, retriever
from app.shared.prompts import prompt
from app.services.chat.schema import ChatRequest
from app.agent_workflow.adapters.orchestrator import engine_event_to_sse
from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.streaming import RunRequest
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
        # StreamingService is a module-level singleton, so a single conversation
        # client here would be shared by concurrent streams and their event logs
        # would cross-contaminate. Hold only an optional injected client (tests);
        # each stream() call otherwise builds its own.
        self._injected_conversation_client = conversation_client
        self.model = model

    def _conversation_client(self) -> BackendConversationClient:
        return self._injected_conversation_client or BackendConversationClient()


    def _stream_agent_workflow(
        self,
        *,
        request: ChatRequest,
        query: str,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        history: list[dict[str, Any]],
        conversation_client: BackendConversationClient,
        events: list[str],
        started_at: float,
    ) -> StreamingResponse:
        config_path = Path(
            os.getenv(
                "AGENT_WORKFLOW_CONFIG",
                str(Path(__file__).resolve().parents[3] / "agent_workflow" / "agents" / "document.yaml"),
            )
        )
        engine = AgentEngine.from_config(config_path)

        def event_stream() -> Iterator[str]:
            yield _sse("meta", {
                "conversation_id": conversation_id,
                "message_id": assistant_message_id,
                "user_message_id": user_message_id,
                "model": self.model,
                "mode": "agent_workflow",
                "sources": [],
                "references": [],
            })

            answer_parts: list[str] = []
            error_message: str | None = None
            tool_call_count = 0
            artifact_count = 0
            review: dict[str, Any] | None = None
            pending_approval: dict[str, Any] | None = None
            thread_id: str | None = None
            events.append("agent_workflow.started")

            try:
                run_request = RunRequest(
                    query=query,
                    session_id=conversation_id,
                    history=history,
                    runtime_context={
                        "user_id": request.user_id,
                        "tenant_id": request.user_id,
                        "role": request.role,
                        "conversation_id": conversation_id,
                    },
                )
                for engine_event in engine.stream(run_request):
                    mapped = engine_event_to_sse(engine_event)
                    if engine_event.get("type") == "agent_activity":
                        tool = engine_event.get("tool", "tool")
                        phase = engine_event.get("phase", "running")
                        events.append(f"agent_workflow.tool {tool} {phase}")
                    if engine_event.get("type") == "pending_approval":
                        events.append(f"agent_workflow.approval_required {engine_event.get('tool')}")
                    if engine_event.get("type") == "done":
                        answer = str(engine_event.get("answer") or "")
                        if not answer_parts and answer:
                            answer_parts.append(answer)
                            yield _sse("delta", {"content": answer})
                        review = engine_event.get("review") if isinstance(engine_event.get("review"), dict) else None
                        tool_call_count = int(engine_event.get("tool_call_count") or 0)
                        artifact_count = int(engine_event.get("artifact_count") or 0)
                        if isinstance(engine_event.get("pending_approval"), dict):
                            pending_approval = engine_event["pending_approval"]
                        thread_id = engine_event.get("thread_id") or thread_id
                        if engine_event.get("error"):
                            error_message = str(engine_event.get("error"))
                        continue
                    if mapped is None:
                        continue
                    event_name, payload = mapped
                    if event_name == "delta":
                        content = str(payload.get("content") or "")
                        if content:
                            answer_parts.append(content)
                            yield _sse("delta", {"content": content})
                    elif event_name in {"agent_activity", "status", "approval_required"}:
                        yield _sse(event_name, payload)
            except Exception as exc:  # noqa: BLE001
                error_message = str(exc)
                events.append("agent_workflow.failed")
                log.warning("agent workflow stream failed", exc_info=True)
                yield _sse("error", {"message": error_message})
            finally:
                answer = "".join(answer_parts)
                latency_ms = _elapsed_ms(started_at)
                completion_tokens = count_tokens(answer) if answer else 0
                events.append("agent_workflow.completed" if not error_message else "agent_workflow.failed")
                logger.info(
                    "chat.completed",
                    outcome="failed" if error_message else "completed",
                    model=self.model,
                    mode="agent_workflow",
                    total_ms=latency_ms,
                    completion_tokens=completion_tokens,
                    tool_call_count=tool_call_count,
                    artifact_count=artifact_count,
                    inference_error=bool(error_message),
                    events=events,
                )

                conversation.persist_assistant_message(
                    request=request,
                    conversation_id=conversation_id,
                    assistant_message_id=assistant_message_id,
                    answer=answer,
                    model=self.model,
                    usage={
                        "prompt_tokens": 0,
                        "completion_tokens": completion_tokens,
                        "total_tokens": completion_tokens,
                    },
                    latency_ms=latency_ms,
                    error_message=error_message,
                    references=[],
                    events=events,
                    status=None,
                )

            yield _sse("done", {
                "conversation_id": conversation_id,
                "message_id": assistant_message_id,
                "latency_ms": _elapsed_ms(started_at),
                "events": events,
                "sources": [],
                "references": [],
                "has_error": error_message is not None,
                "error": error_message,
                "review": review,
                "artifact_count": artifact_count,
                "tool_call_count": tool_call_count,
                "mode": "agent_workflow",
                # Present when the run paused on a destructive-tool approval;
                # resume via AgentEngine.resume(thread_id, approved=...).
                "pending_approval": pending_approval,
                "thread_id": thread_id,
            })

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

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
        conversation_client = self._conversation_client()

        # ── Conversation setup ────────────────────────────────────────────────
        try:
            conversation_id, user_message_id, assistant_message_id = (
                conversation.init_conversation(
                    conversation_client, request, query, self.model,
                    events, latencies_ms,
                )
            )
            history = conversation.load_history(
                conversation_client,
                request.user_id,
                conversation_id,
                {user_message_id, assistant_message_id},
                events,
                latencies_ms,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        if is_enabled("chat.agent_workflow"):
            return self._stream_agent_workflow(
                request=request,
                query=query,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                history=history,
                conversation_client=conversation_client,
                events=events,
                started_at=started_at,
            )

        # ── Retrieval ─────────────────────────────────────────────────────────
        context_texts: list[str] = []
        references: list[dict[str, Any]] = []
        if vector_store is not None:
            retrieval_started = time.perf_counter()
            try:
                retrieval_result = retriever.retrieve_context_result(
                    vector_store, query, request.user_id, request.k, request.role, history,
                )
                context_texts = retrieval_result.context_texts
                references = retrieval_result.references
                history = retrieval_result.bounded_history
                events.extend(retrieval_result.events)
                latencies_ms["retrieval_ms"] = _elapsed_ms(retrieval_started)
            except Exception:
                latencies_ms["retrieval_ms"] = _elapsed_ms(retrieval_started)
                events.append("retrieval.failed")
                logger.exception("retrieval.failed", retrieval_ms=latencies_ms["retrieval_ms"])

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
                "sources": [reference["note_id"] for reference in references],
                "references": references,
            })

            answer_parts: list[str] = []
            error_message: str | None = None
            usage: dict[str, int] = {
                "prompt_tokens": prompt_tokens_estimate,
                "completion_tokens": 0,
                "total_tokens": prompt_tokens_estimate,
            }
            model_reported_usage = False
            was_cancelled = False
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
            except GeneratorExit:
                was_cancelled = True
                events.append("client.disconnected")
                raise
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
            finally:
                answer = "".join(answer_parts)
                latencies_ms["inference_ms"] = _elapsed_ms(inference_started)
                latencies_ms["total_ms"] = _elapsed_ms(started_at)
                events.append(
                    "llm.stream.cancelled" if was_cancelled
                    else "llm.stream.completed" if not error_message
                    else "llm.stream.failed"
                )

                if not usage.get("completion_tokens"):
                    usage["completion_tokens"] = count_tokens(answer) if answer else 0
                if not model_reported_usage or not usage.get("total_tokens"):
                    usage["total_tokens"] = (
                        usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                    )

                outcome = "cancelled" if was_cancelled else "failed" if error_message else "completed"
                logger_method = logger.error if error_message else logger.info
                logger_method(
                    "chat.completed",
                    outcome=outcome,
                    model=self.model,
                    chat_system_version=ACTIVE_CHAT_SYSTEM_VERSION,
                    context_chunk_count=len(context_texts),
                    source_count=len(references),
                    retrieval_ms=latencies_ms.get("retrieval_ms", 0),
                    prompt_ms=latencies_ms.get("prompt_ms", 0),
                    first_token_ms=latencies_ms.get("first_token_ms", 0),
                    inference_ms=latencies_ms["inference_ms"],
                    total_ms=latencies_ms["total_ms"],
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    cancelled=was_cancelled,
                    inference_error=bool(error_message),
                    events=events,
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
                    references=references,
                    events=events,
                    status="partial" if was_cancelled else None,
                )

            yield _sse("done", {
                "conversation_id": conversation_id,
                "message_id": assistant_message_id,
                "latency_ms": latencies_ms["total_ms"],
                "latencies_ms": latencies_ms,
                "usage": usage,
                "events": events,
                "sources": [reference["note_id"] for reference in references],
                "references": references,
                "has_error": error_message is not None,
            })

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
