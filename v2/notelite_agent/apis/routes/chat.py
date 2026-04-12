"""Streaming chat endpoint — SSE with write-ahead persistence."""

import json
import logging
import time

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from apis.schema import ChatRequest
from core.config import CHAT_LLM_API_BASE, LLM_API_KEY
from core.contracts import AccessContext
from services.retrieval import VectorStore
from services import backend_client
from workers.tasks import persist_message

log = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/stream")
def chat_stream(request: ChatRequest):
    """SSE streaming chat with write-ahead persistence.

    Flow:
    1. Create/reuse conversation → write-ahead user + assistant (partial) messages
    2. Retrieve context from Qdrant
    3. Call inference (blocking — server doesn't support SSE)
    4. Stream response word-by-word to FE via SSE
    5. Fire Celery task to finalize the assistant message
    """
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
    access_context = AccessContext(
        user_id=request.user_id,
        role=request.role,
        tenant_id=request.tenant_id,
    )
    with VectorStore() as db:
        results = db.retrieve_documents(
            request.query, k=request.k, access_context=access_context,
        )

    context = "\n\n".join(doc.text for doc in results)
    source_ids = [doc.metadata.get("note_id") for doc in results if doc.metadata.get("note_id")]

    # ── 3. Inference (via chat LLM) ──────────────────────────────────────
    chat_messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful personal assistant that answers questions about the user's notes.\n\n"
                "Rules:\n"
                "- Answer using ONLY information from the provided context. Never use outside knowledge.\n"
                "- Be conversational and direct — write naturally, like explaining to a friend.\n"
                "- If the context does not contain enough information, say so honestly in one sentence.\n"
                "- Do not invent details, steps, or facts not present in the context."
            ),
        },
        {
            "role": "user",
            "content": f"Context from my notes:\n{context}\n\nQuestion: {request.query}",
        },
    ]

    answer = ""
    error = None
    tokens_used = 0
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
        tokens_used = body.get("usage", {}).get("total_tokens", 0)
    except httpx.ConnectError:
        log.error("Chat inference unreachable at %s — is the inference container running?", CHAT_LLM_API_BASE)
        error = f"Inference service unreachable at {CHAT_LLM_API_BASE}. Start the chat inference container (port 8082)."
    except Exception:
        log.exception("Chat inference failed")
        error = "Inference service error"

    latency_ms = int((time.monotonic() - start_ms) * 1000)

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
            "latency_ms": latency_ms,
            "sources": list(set(source_ids)),
        })

        persist_message.delay({
            "user_id": request.user_id,
            "conversation_id": conv_id,
            "message_id": assistant_msg["id"],
            "content": answer,
            "status": "error" if error else "complete",
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "sources_used": list(set(source_ids)),
            "error_message": error,
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")
