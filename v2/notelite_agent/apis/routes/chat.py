"""Streaming chat endpoint — SSE with write-ahead persistence."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

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
from pipeline.rewrite import rewrite_query
from pipeline.strategies import execute as execute_strategy
from services.retrieval import VectorStore
from services import backend_client
from workers.tasks import persist_message

log = structlog.get_logger()

MAX_HISTORY_MESSAGES = 16  # 8 turns × 2 (user + assistant)

_CLARIFY_GENERIC = (
    "I'm not sure what you're looking for. Could you ask a specific "
    "question about your notes? For example:\n"
    '- "What did I write about project X?"\n'
    '- "List all my notes about travel"\n'
    '- "How many times did I mention budgeting?"'
)

_CLARIFY_SYSTEM = (
    "The user sent an ambiguous query to a personal notes assistant. "
    "Based on the conversation so far, generate ONE short clarifying "
    "question (1-2 sentences) that helps narrow down what they want "
    "from their notes. Do NOT answer the query — only ask for clarification."
)


def _build_clarification(query: str, history: list[dict]) -> str:
    """Return a clarifying question — LLM-generated if history exists,
    otherwise a generic prompt."""
    if not history:
        return _CLARIFY_GENERIC
    try:
        body = llm_call(
            {
                "model": "llama3.1",
                "messages": [
                    {"role": "system", "content": _CLARIFY_SYSTEM},
                    *history[-6:],
                    {"role": "user", "content": query},
                ],
                "max_tokens": 128,
                "temperature": 0.3,
            },
            timeout=30.0,
        )
        return body["choices"][0]["message"]["content"].strip()
    except Exception:
        log.warning("chat.clarify_llm_failed", exc_info=True)
        return _CLARIFY_GENERIC


router = APIRouter(tags=["chat"], dependencies=[Depends(require_feature("chat"))])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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

    with ThreadPoolExecutor(max_workers=2) as pool:
        user_msg_future = pool.submit(
            backend_client.create_message,
            request.user_id, conv_id, role="user", content=request.query,
        )
        assistant_msg_future = pool.submit(
            backend_client.create_message,
            request.user_id, conv_id, role="assistant", content="", status="partial",
        )
        user_msg = user_msg_future.result()
        assistant_msg = assistant_msg_future.result()

    # ── 1b. Fetch conversation history ──────────────────────────────────
    history_messages = []
    rewrite_ms = 0
    search_query = request.query  # query used for retrieval (may be rewritten)

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
    plan = planner.plan(request.query)
    intent_ms = int((time.monotonic() - intent_start) * 1000)

    # ── 2a. clarify_intent short-circuit ─────────────────────────────────
    if plan.intent == "clarify_intent":
        answer = _build_clarification(request.query, history_messages)
        log.info(
            "chat.clarify_intent",
            conv_id=conv_id,
            user_id=request.user_id,
            query=request.query,
            intent_latency_ms=intent_ms,
        )
        retrieval_ms = 0
        inference_ms = 0
        tokens_used = 0
        prompt_tokens = 0
        completion_tokens = 0
        source_ids: list[str] = []
        error = None

    else:
        # ── 2b. RAG retrieval ────────────────────────────────────────────
        retrieval_start = time.monotonic()
        access_context = AccessContext(
            user_id=request.user_id,
            role=request.role,
            tenant_id=request.tenant_id,
        )

        with VectorStore() as db:
            results = db.retrieve_documents(
                search_query, k=request.k, access_context=access_context,
            )

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
            search_query=search_query,
            strategy=plan.strategy,
            intent=plan.intent,
            search_term=plan.search_term,
            source=plan.source,
            confidence=plan.confidence,
            intent_latency_ms=intent_ms,
            strategy_latency_ms=strategy_ms,
            rewrite_latency_ms=rewrite_ms,
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

        # ── 3. Build prompt ──────────────────────────────────────────────
        system_content = (
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
            "- Never start responses with 'Based on our conversation so far' or similar preamble.\n"
            "- NEVER echo passwords, secrets, or API keys from the context. "
            "If the user asks about credentials, confirm they exist and where, but mask the values "
            "(e.g. 'Username: Cisco***', 'Password: ****').\n"
            "- When a 'Verified fact' section is present, treat it as ground truth. Use the information "
            "naturally in your answer without mentioning 'Verified fact' or explaining where the data came from."
        )

        if history_messages:
            history_block = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in history_messages
            )
            system_content += (
                "\n\nPrevious conversation (for reference — use to resolve pronouns, "
                "follow-ups, and questions about the conversation itself, "
                "but do NOT treat old answers as factual sources for note-related questions):\n"
                + history_block
            )

        skip_context = strategy_result.skip_context if strategy_result else False

        if skip_context and fact:
            user_content = f"Verified fact: {fact}\n\nQuestion: {search_query}"
        else:
            user_content = f"Context from my notes:\n{context}"
            if fact:
                user_content += f"\n\nVerified fact: {fact}"
            user_content += f"\n\nQuestion: {search_query}"

        chat_messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        # ── 4. Inference ─────────────────────────────────────────────────
        answer = ""
        error = None
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
