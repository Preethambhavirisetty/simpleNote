"""Streaming chat endpoint — SSE with write-ahead persistence."""

import json
import time
import httpx
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from apis.schema import ChatCompletionModel, ChatRequest
from core.config import CHAT_LLM_API_BASE
from core.contracts import AccessContext
from core.feature_flags import is_enabled, require_feature
from pipeline.llm import llm_call
from pipeline.intent import QueryPlanner
from pipeline.intent_handlers import handle_intent
from pipeline.rewrite import rewrite_query
from services import backend_client
from workers.tasks import persist_message

log = structlog.get_logger()

MAX_HISTORY_MESSAGES = 16  # 8 turns × 2 (user + assistant)

_RAG_SYSTEM = (
    "You are a helpful personal assistant that answers questions about the user's notes.\n\n"
    "Rules:\n"
    "- Answer using ONLY the 'Context from my notes' or 'Verified fact' in the current message. "
    "These are freshly retrieved from the user's notes and are the sole source of truth.\n"
    "- Use the Previous conversation ONLY to understand what 'it', 'that', 'the same one', etc. "
    "refer to, or to answer meta-questions like 'what did I ask earlier?'. "
    "NEVER pull facts, details, or quotes from prior answers — they may be outdated.\n"
    "- Be conversational and direct — write naturally, like explaining to a friend.\n"
    "- If the context does not contain enough information, say so honestly in one sentence. "
    "Do NOT fill gaps with information from prior answers.\n"
    "- Do not invent details, steps, or facts.\n"
    "- Never start responses with 'Based on our conversation so far', "
    "'Context from my notes', or similar preamble.\n"
    "- NEVER echo passwords, secrets, or API keys from the context. "
    "If the user asks about credentials, confirm they exist and where, but mask the values "
    "(e.g. 'Username: Cisco***', 'Password: ****').\n"
    "- When a 'Verified fact' section is present, treat it as ground truth. Use the information "
    "naturally in your answer without mentioning 'Verified fact' or explaining where the data came from."
)

router = APIRouter(tags=["chat"], dependencies=[Depends(require_feature("chat"))])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_rag_prompt(
    context: str,
    fact: str | None,
    skip_context: bool,
    search_query: str,
    history: list[dict],
) -> list[dict]:
    """Build the system + user messages for the RAG LLM call."""
    system = _RAG_SYSTEM
    if history:
        history_block = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in history
        )
        system += (
            "\n\nPrevious conversation (for reference — use to resolve pronouns, "
            "follow-ups, and questions about the conversation itself, "
            "but do NOT treat old answers as factual sources for note-related questions):\n"
            + history_block
        )

    if skip_context and fact:
        user_content = f"Verified fact: {fact}\n\nQuestion: {search_query}"
    else:
        user_content = f"Context from my notes:\n{context}"
        if fact:
            user_content += f"\n\nVerified fact: {fact}"
        user_content += f"\n\nQuestion: {search_query}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


@router.post("/chat/completions")
def chat_completions(request: ChatCompletionModel):
    return llm_call(request)


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

    # ── 1b. Fetch conversation history + rewrite query ──────────────────────────────────
    history_messages: list[dict] = []
    rewrite_ms = 0
    search_query = request.query

    if request.conversation_id:
        exclude_ids = {user_msg["id"], assistant_msg["id"]}
        raw = backend_client.get_messages(request.user_id, conv_id)
        for m in raw:
            if m["id"] in exclude_ids:
                continue
            if m["role"] == "assistant" and m.get("status") != "complete":
                continue
            history_messages.append({"role": m["role"], "content": m["content"]})
        history_messages = history_messages[-MAX_HISTORY_MESSAGES:]

        if history_messages and is_enabled("chat.query_rewrite"):
            search_query, rewrite_ms = rewrite_query(request.query, history_messages)

    # ── 2. Intent detection ──────────────────────────────────────────────
    intent_start = time.monotonic()
    planner = QueryPlanner()
    plan = planner.plan(request.query) # intent detected with a strategy
    intent_ms = int((time.monotonic() - intent_start) * 1000)

    # ── 3. Intent-specific retrieval ─────────────────────────────────────
    access_context = AccessContext(
        user_id=request.user_id,
        role=request.role,
        tenant_id=request.tenant_id,
    )
    result = handle_intent(
        plan, request.query, search_query,
        access_context, history_messages, request.k,
    )

    log.info(
        "chat.intent",
        conv_id=conv_id,
        user_id=request.user_id,
        query=request.query,
        search_query=search_query,
        strategy=plan.strategy,
        intent=plan.intent,
        search_term=plan.search_term,
        extracted_terms=result.extracted_terms or None,
        source=plan.source,
        confidence=plan.confidence,
        intent_latency_ms=intent_ms,
        retrieval_ms=result.retrieval_ms,
        strategy_ms=result.strategy_ms,
        rewrite_latency_ms=rewrite_ms,
    )

    # ── 4. Generate response ─────────────────────────────────────────────
    error = None
    citations = result.citations

    if result.answer is not None:
        answer = result.answer
        source_ids = result.source_ids
        retrieval_ms = result.retrieval_ms
        inference_ms = result.inference_ms
        tokens_used = result.tokens_used
        prompt_tokens = result.prompt_tokens
        completion_tokens = result.completion_tokens

    else:
        source_ids = result.source_ids
        retrieval_ms = result.retrieval_ms

        chat_messages = _build_rag_prompt(
            result.context, result.fact, result.skip_context,
            search_query, history_messages,
        )

        answer = ""
        tokens_used = 0
        prompt_tokens = 0
        completion_tokens = 0
        inference_start = time.monotonic()
        try:
            body = llm_call(
                {"model": "llama3.1", "messages": chat_messages, "max_tokens": 1024},
                timeout=300.0,
            )
            answer = body["choices"][0]["message"]["content"]
            usage = body.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            tokens_used = usage.get("total_tokens", 0)
        except httpx.ConnectError:
            log.error("chat.inference_unreachable", target=CHAT_LLM_API_BASE)
            error = (
                f"Inference service unreachable at {CHAT_LLM_API_BASE}. "
                "Start the chat inference container (port 8082)."
            )
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

    # ── 5. Stream response as SSE ────────────────────────────────────────
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

        done_payload: dict = {
            "latency_ms": total_latency_ms,
            "sources": list(set(source_ids)),
        }
        if citations:
            done_payload["citations"] = citations
        yield _sse("done", done_payload)

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
            "sources_used": citations if citations else list(set(source_ids)),
            "error_message": error,
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")
