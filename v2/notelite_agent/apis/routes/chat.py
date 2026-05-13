"""Streaming chat — SSE with RunPod OpenAI-compatible streaming (primary → fallback)."""

from __future__ import annotations

import json
import time

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from apis.schema import ChatCompletionModel, ChatRequest
from core.contracts import AccessContext
from core.feature_flags import is_enabled, require_feature
from core.settings import init_llama_index_settings
from pipeline.llm import llm_call
from pipeline.intent import QueryPlanner
from pipeline.intent_handlers import HandlerResult, handle_intent
from services import backend_client
from services.inference_stream import stream_chat_completions
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


_CLARIFY_SYSTEM = (
    "The user sent an ambiguous query to a personal notes assistant. "
    "Based on the conversation so far, generate ONE short clarifying "
    "question (1-2 sentences) that helps narrow down what they want "
    "from their notes. Do NOT answer the query — only ask for clarification."
)

_CONVERSATION_META_SYSTEM = (
    "You are a personal notes assistant. The user is asking about "
    "this conversation, not their notes. Answer based on the "
    "conversation history below. If they are saying goodbye, "
    "respond warmly and briefly."
)

_CLARIFY_FALLBACK = (
    "I'm not sure what you're looking for. Could you ask a specific "
    "question about your notes? For example:\n"
    '- "What did I write about project X?"\n'
    '- "List all my notes about travel"\n'
    '- "How many times did I mention budgeting?"'
)


def _build_clarify_messages(query: str, history: list[dict]) -> list[dict]:
    system = _CLARIFY_SYSTEM
    if not history:
        system += (
            " There is no prior conversation in this thread yet — give one short, "
            "friendly clarifying question and optionally one example of how to ask about their notes."
        )
    messages: list[dict] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": query})
    return messages


def _build_conversation_meta_messages(query: str, history: list[dict]) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": _CONVERSATION_META_SYSTEM}]
    if history:
        messages.extend(history[-10:])
    messages.append({"role": "user", "content": query})
    return messages


def _build_final_llm_messages(
    result: HandlerResult,
    raw_query: str,
    search_query: str,
    history: list[dict],
) -> list[dict]:
    """Select the final chat prompt after retrieval."""
    if result.response_mode == "clarify":
        return _build_clarify_messages(raw_query, history)
    if result.response_mode == "conversation_meta":
        return _build_conversation_meta_messages(raw_query, history)
    return _build_rag_prompt(
        result.context,
        result.fact,
        result.skip_context,
        search_query,
        history,
    )


def _llm_config_for_mode(response_mode: str) -> tuple[int, float, float | None]:
    match response_mode:
        case "clarify":
            return 128, 30.0, 0.3
        case "conversation_meta":
            return 256, 60.0, None
        case _:
            return 1024, 300.0, None


def _initiate_conversation(request: ChatRequest, query: str) -> tuple[dict, dict, str]:
    conv_id = request.conversation_id
    if not conv_id:
        conv = backend_client.create_conversation(
            request.user_id,
            title=request.conversation_title or query[:100],
        )
        conv_id = conv["id"]

    user_msg = backend_client.create_message(
        request.user_id, conv_id, role="user", content=query,
    )
    assistant_msg = backend_client.create_message(
        request.user_id, conv_id, role="assistant", content="", status="partial",
    )
    return user_msg, assistant_msg, conv_id


def _load_history(
    user_id: str,
    conv_id: str,
    user_msg: dict,
    assistant_msg: dict,
) -> list[dict]:
    history_messages: list[dict] = []
    exclude_ids = {user_msg["id"], assistant_msg["id"]}
    raw = backend_client.get_messages(user_id, conv_id)
    for m in raw:
        if m["id"] in exclude_ids:
            continue
        if m["role"] == "assistant" and m.get("status") != "complete":
            continue
        history_messages.append({"role": m["role"], "content": m["content"]})
    return history_messages[-MAX_HISTORY_MESSAGES:]


@router.post("/chat/completions")
def chat_completions(request: ChatCompletionModel):
    # return llm_call(request)
    print(request)
    return {"message": "data"}


@router.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """SSE: meta → token deltas from RunPod stream → done + persist."""
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    init_llama_index_settings()

    start_ms = time.monotonic()
    user_msg, assistant_msg, conv_id = _initiate_conversation(request, query)
    history_messages = _load_history(request.user_id, conv_id, user_msg, assistant_msg)

    search_query = request.query

    intent_start = time.monotonic()
    planner = QueryPlanner()
    plan = planner.plan(query)
    intent_ms = int((time.monotonic() - intent_start) * 1000)

    access_context = AccessContext(
        user_id=request.user_id,
        role=request.role,
        tenant_id=request.tenant_id,
    )
    retrieval_start = time.monotonic()
    strategy_result = handle_intent(plan.intent, search_query, access_context, history_messages, request.k)
    retrieval_ms = int((time.monotonic() - retrieval_start) * 1000)

    log.info(
        "chat.intent",
        conv_id=conv_id,
        user_id=request.user_id,
        query=request.query,
        search_query=search_query,
        intent=plan.intent,
        strategy=plan.strategy,
        source=plan.source,
        confidence=plan.confidence,
        intent_latency_ms=intent_ms,
        retrieval_ms=retrieval_ms,
    )

    chat_messages = _build_final_llm_messages(
        strategy_result, request.query, search_query, history_messages,
    )
    max_tokens, llm_timeout, llm_temperature = _llm_config_for_mode(strategy_result.response_mode)

    def event_stream():
        yield _sse("meta", {
            "conversation_id": conv_id,
            "message_id": assistant_msg["id"],
            "user_message_id": user_msg["id"],
        })

        answer_parts: list[str] = []
        error_message: str | None = None
        prompt_tokens = 0
        completion_tokens = 0
        tokens_used = 0
        inference_start = time.monotonic()

        try:
            for evt in stream_chat_completions(
                chat_messages,
                max_tokens=max_tokens,
                temperature=llm_temperature,
                timeout=llm_timeout,
            ):
                et = evt.get("type")
                if et == "content_delta" and evt.get("content"):
                    piece = evt["content"]
                    answer_parts.append(piece)
                    yield _sse("delta", {"content": piece})
                elif et == "usage" and evt.get("usage"):
                    u = evt["usage"]
                    prompt_tokens = u.get("prompt_tokens", prompt_tokens)
                    completion_tokens = u.get("completion_tokens", completion_tokens)
                    tokens_used = u.get("total_tokens", tokens_used)
                elif et == "error":
                    error_message = evt.get("message", "Inference error")
                    log.error("chat.stream_inference_error", detail=error_message)
                    yield _sse("error", {"message": error_message})
                    break
        except httpx.HTTPError as e:
            error_message = str(e)
            log.error("chat.stream_http_error", exc_info=True)
            yield _sse("error", {"message": error_message})
        except Exception:
            error_message = "Inference service error"
            log.error("chat.stream_error", exc_info=True)
            yield _sse("error", {"message": error_message})

        answer = "".join(answer_parts)
        if error_message and strategy_result.response_mode == "clarify":
            answer = _CLARIFY_FALLBACK
        elif error_message and strategy_result.response_mode == "conversation_meta":
            answer = "Sorry, I couldn't process that. Could you try again?"

        inference_ms = int((time.monotonic() - inference_start) * 1000)
        total_latency_ms = int((time.monotonic() - start_ms) * 1000)

        log.info(
            "chat.inference",
            conv_id=conv_id,
            user_id=request.user_id,
            latency_ms=inference_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=tokens_used,
            error=error_message,
        )

        source_ids = list(dict.fromkeys(strategy_result.source_ids))
        citations = strategy_result.citations

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
            has_error=error_message is not None,
        )

        persist_message.delay({
            "user_id": request.user_id,
            "conversation_id": conv_id,
            "message_id": assistant_msg["id"],
            "content": answer,
            "status": "error" if error_message else "complete",
            "latency_ms": total_latency_ms,
            "tokens_used": tokens_used,
            "sources_used": citations if citations else list(set(source_ids)),
            "error_message": error_message,
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# curl --location 'http://localhost:3002/api/chat/completions' \
# --header 'x-api-key: 029cdc955484f1e96171fc5aa723e1979a5f3f4209627b49db976eb6578874a0' \
# --header 'Content-Type: application/json' \
# --data '{
#     "model": "mistral-7b",
#     "messages": [
#       {
#         "role": "system",
#         "content": "You are a story telling assistant."
#       },
#       {
#         "role": "user",
#         "content": "who are you?"
#       }
#     ],
#     "temperature": 0.2,
#     "max_tokens": 256,
#     "stream": false
#   }'