"""Streaming chat endpoint — SSE with write-ahead persistence."""

import json
import time

import httpx
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from apis.schema import ChatRequest
from core.config import CHAT_LLM_API_BASE, LLM_API_KEY
from core.contracts import AccessContext
from core.feature_flags import require_feature
from pipeline.intent import QueryPlanner
from pipeline.strategies import execute as execute_strategy
from services.retrieval import VectorStore
from services import backend_client
from workers.tasks import persist_message

log = structlog.get_logger()

router = APIRouter(tags=["chat"], dependencies=[Depends(require_feature("chat"))])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """SSE streaming chat with write-ahead persistence."""
    start_ms = time.monotonic()

    # ── 1. Conversation bookkeeping ──────────────────────────────────────
    conv_id = request.conversation_id
    if not conv_id:
        conv = backend_client.create_conversation(
            request.user_id,
            title=request.conversation_title or request.query[:100],
        )
        conv_id = conv["id"]

    user_msg = backend_client.create_message(
        request.user_id, conv_id, role="user", content=request.query,
    )

    assistant_msg = backend_client.create_message(
        request.user_id, conv_id, role="assistant", content="", status="partial",
    )

    # ── 2. RAG retrieval ─────────────────────────────────────────────────
    retrieval_start = time.monotonic()
    access_context = AccessContext(
        user_id=request.user_id,
        role=request.role,
        tenant_id=request.tenant_id,
    )
    with VectorStore() as db:
        results = db.retrieve_documents(
            request.query, k=request.k, access_context=access_context,
        )

        # ── 2b. Intent detection + strategy execution ────────────────────
        intent_start = time.monotonic()
        planner = QueryPlanner()
        plan = planner.plan(request.query)
        intent_ms = int((time.monotonic() - intent_start) * 1000)

        strategy_result = None
        if plan.strategy != "semantic":
            strategy_start = time.monotonic()
            all_chunks = db.scroll_all_chunks(access_context)
            strategy_result = execute_strategy(plan, all_chunks)
            strategy_ms = int((time.monotonic() - strategy_start) * 1000)
        else:
            strategy_ms = 0

        log.info(
            "chat.intent",
            conv_id=conv_id,
            user_id=request.user_id,
            query=request.query,
            strategy=plan.strategy,
            search_term=plan.search_term,
            source=plan.source,
            confidence=plan.confidence,
            intent_latency_ms=intent_ms,
            strategy_latency_ms=strategy_ms,
        )

    context = "\n\n".join(doc.text for doc in results)
    source_ids = list(dict.fromkeys(doc.metadata.get("note_id") for doc in results if doc.metadata.get("note_id")))
    retrieval_ms = int((time.monotonic() - retrieval_start) * 1000)

    fact = strategy_result.fact if strategy_result else None
    if strategy_result and strategy_result.source_ids:
        for sid in strategy_result.source_ids:
            if sid not in source_ids:
                source_ids.append(sid)

    log.info(
        "chat.retrieval",
        conv_id=conv_id,
        user_id=request.user_id,
        query=request.query,
        result_count=len(results),
        result_ids=[r.id_ for r in results],
        source_ids=source_ids,
        fact=fact,
        latency_ms=retrieval_ms,
    )

    # ── 3. Inference (via chat LLM) ──────────────────────────────────────
    system_content = (
        "You are a helpful personal assistant that answers questions about the user's notes.\n\n"
        "Rules:\n"
        "- Answer using ONLY information from the provided context. Never use outside knowledge.\n"
        "- Be conversational and direct — write naturally, like explaining to a friend.\n"
        "- If the context does not contain enough information, say so honestly in one sentence.\n"
        "- Do not invent details, steps, or facts not present in the context.\n"
        "- When a 'Verified fact' section is present, treat it as ground truth and incorporate it "
        "into your answer directly. Do not contradict or re-count it."
    )

    user_content = f"Context from my notes:\n{context}"
    if fact:
        user_content += f"\n\nVerified fact: {fact}"
    user_content += f"\n\nQuestion: {request.query}"

    chat_messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    answer = ""
    error = None
    tokens_used = 0
    prompt_tokens = 0
    completion_tokens = 0
    inference_start = time.monotonic()
    try:
        resp = httpx.post(
            f"{CHAT_LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={"model": "llama3.1", "messages": chat_messages, "max_tokens": 1024},
            timeout=300.0,
        )
        resp.raise_for_status()
        body = resp.json()
        answer = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        tokens_used = usage.get("total_tokens", 0)
    except httpx.ConnectError:
        log.error("chat.inference_unreachable", target=CHAT_LLM_API_BASE)
        error = f"Inference service unreachable at {CHAT_LLM_API_BASE}. Start the chat inference container (port 8082)."
    except Exception:
        log.error("chat.inference_error", exc_info=True)
        error = "Inference service error"

    inference_ms = int((time.monotonic() - inference_start) * 1000)

    log.info(
        "chat.inference",
        conv_id=conv_id,
        user_id=request.user_id,
        latency_ms=inference_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=tokens_used,
        error=error,
    )

    total_latency_ms = int((time.monotonic() - start_ms) * 1000)

    # ── 4. Stream response as SSE ────────────────────────────────────────
    def event_stream():
        yield _sse("meta", {
            "conversation_id": conv_id,
            "message_id": assistant_msg["id"],
            "user_message_id": user_msg["id"],
        })

        if error:
            yield _sse("error", {"message": error})
        else:
            words = answer.split(" ")
            for i, word in enumerate(words):
                token = word if i == 0 else " " + word
                yield _sse("delta", {"content": token})
                time.sleep(0.02)

        yield _sse("done", {
            "latency_ms": total_latency_ms,
            "sources": list(set(source_ids)),
        })

        log.info(
            "chat.complete",
            conv_id=conv_id,
            user_id=request.user_id,
            latency_ms=total_latency_ms,
            retrieval_ms=retrieval_ms,
            inference_ms=inference_ms,
            total_tokens=tokens_used,
            has_error=error is not None,
        )

        persist_message.delay({
            "user_id": request.user_id,
            "conversation_id": conv_id,
            "message_id": assistant_msg["id"],
            "content": answer,
            "status": "error" if error else "complete",
            "latency_ms": total_latency_ms,
            "tokens_used": tokens_used,
            "sources_used": list(set(source_ids)),
            "error_message": error,
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")
