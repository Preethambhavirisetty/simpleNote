import json
import logging
import secrets
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader

from apis.schema import ChatRequest, IngestionRequest, RetrieveRequest
from apis.worker import ingest_in_background, persist_message, worker_app
from core.config import AGENT_API_KEY, CHAT_LLM_API_BASE, LLM_API_KEY
from core.contracts import AccessContext
from services.storage_service import VectorStore
from services import backend_client
from llama_index.core import Settings
from llama_index.core.llms import ChatMessage, MessageRole

log = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Reject requests that don't carry the correct shared secret."""
    if not key or not secrets.compare_digest(key, AGENT_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


router = APIRouter(
    prefix="/api",
    tags=["ingestion", "retrieval"],
    dependencies=[Depends(_require_api_key)],   # applied to every route in this router
)


@router.get("/status/{task_id}")
def get_status(task_id: str):
    result = worker_app.AsyncResult(task_id)
    inspector = worker_app.control.inspect(timeout=1.0)
    active_workers = inspector.ping() or {}
    worker_available = len(active_workers) > 0

    state = result.state
    diagnostics = None
    if state == "PENDING" and not worker_available:
        diagnostics = "No active Celery workers detected."

    return {
        "status": state,
        "result": result.result if result.ready() else None,
        "worker_available": worker_available,
        "diagnostics": diagnostics,
    }


@router.post('/ingest')
def ingest_data_to_vector_store(request: IngestionRequest):
    """
    {
        "user_id": "SAMPLEUSER01",
        "role": "user",
        "tenant_id": "TENANT01",
        "folder_id": "SAMPLESFOLDER01",
        "note_id": "SAMPLENOTE01",
        "folder_title": "SAMPLE FOLDER TITLE1",
        "note_title": "SAMPLE NOTE TITLE1",
        "description": "SAMPLE DESCRIPTION 1",
        "tags": [
            "tag1",
            "tag2"
        ],
      "text": "The \"System Failure\" Stress Test\ntext\nUPLOADED_FILE_FINAL_v2_USE_THIS_ONE.txt\nUser: @Marketing_Lead | Date: 2026-05-12\n\n\n1. CAMPAIGN OVERVIEW\nWe are launching \"Project Zenith.\" It's going to be huge.\n   \n   \n2. AUDIENCE SEGMENTATION (DRAFT)\n* Tier 1: Early Adopters\n    - Age: 18-24\n    - Interest: Tech, AI, \"Crypto\"\n        * Note: Re-verify the crypto segment.\n* Tier 2: Enterprise\n    - Size: 500+ Employees\n\n3. TRACKING PIXEL CODE\nAdd this to the <head> of the landing page:\n\n```javascript\n// Do not modify the ID below\nconst pixelId = \"PX-9900-ALPHA\";\nconsole.log(\"Pixel Initialized for \" + pixelId);\n/* \n  Fallback logic for legacy \n  browsers starts here \n*/\ninit_fallback();\nUse code with caution.\n```\n\nBUDGET BREAKDOWN (PASTED FROM EXCEL)\nCategory Amount Status Owner\nAds $50,000 Approved @John\nSocial $12,000 Pending @Sarah\nInfluencers $30,000 Review @Mike\nOFFICE LOCATIONS & HOURS\nHeadquarters: 555 Innovation Drive\nFloor 12, Suite 400\nAustin, TX 78701\nHours: 9am - 6pm (Mon-Fri)\nTO-DO LIST\nDesign the logo\nHire a copywriter\nPrepare the @Legal_Team brief\nRANDOM THOUGHTS...\nMaybe we should use more blue? Or teal?\nUpdate: Blue is confirmed.\n[END OF TRANSMISSION]"
    }
    """
    print(f"Ingesting note for: {request.user_id}!")
    data = request.to_ingestion_payload()
    # job = ingest_in_background.apply_async(args=[data])
    job = ingest_in_background.delay(data)
    return {"job_id": job.id}


@router.post('/get-context')
def get_context(request: RetrieveRequest):
    access_context = AccessContext(
        user_id=request.user_id,
        role=request.role,
        tenant_id=request.tenant_id,
    )
    with VectorStore() as db:
        results = db.retrieve_documents(
            request.query,
            k=request.k,
            access_context=access_context,
        )

    context = "\n\n".join(doc.text for doc in results)
    return {"context": context}


@router.post('/chat')
def ask_llm(request: RetrieveRequest):
    access_context = AccessContext(
        user_id=request.user_id,
        role=request.role,
        tenant_id=request.tenant_id,
    )
    with VectorStore() as db:
        results = db.retrieve_documents(
            request.query,
            k=request.k,
            access_context=access_context,
        )

    context = "\n\n".join(doc.text for doc in results)

    messages = [
        ChatMessage(
            role=MessageRole.SYSTEM,
            content=(
                "You are a helpful personal assistant that answers questions about the user's notes.\n\n"
                "Rules:\n"
                "- Answer using ONLY information from the provided context. Never use outside knowledge.\n"
                "- Be conversational and direct — write naturally, like explaining to a friend.\n"
                "- If the context does not contain enough information, say so honestly in one sentence.\n"
                "- Do not invent details, steps, or facts not present in the context."
            ),
        ),
        ChatMessage(
            role=MessageRole.USER,
            content=f"Context from my notes:\n{context}\n\nQuestion: {request.query}",
        ),
    ]
    response = Settings.llm.chat(messages)
    return {"answer": response.message.content}


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

    # ── 1. Conversation bookkeeping ───────────────────────────────────────────
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

    # ── 2. RAG retrieval ─────────────────────────────────────────────────────
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

    # ── 3. Inference (via chat LLM, not summarization) ─────────────────────
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
    except Exception as e:
        log.exception("Chat inference failed")
        error = str(e)

    latency_ms = int((time.monotonic() - start_ms) * 1000)

    # ── 4. Stream response as SSE ────────────────────────────────────────────
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

        # ── 5. Async persistence ─────────────────────────────────────────
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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


""" Backup prompt
    messages = [
        ChatMessage(
            role=MessageRole.SYSTEM,
            content=(
                "You are a strict note-retrieval assistant. Your only source of truth is the context below. "
                "Follow every rule exactly:\n\n"
                "1. NEVER use knowledge from outside the provided context. If it is not in the context, it does not exist.\n"
                "2. Do NOT add, invent, or embellish any step, fact, or detail that is not explicitly stated in the context.\n"
                "3. If the context contains conflicting rules or guidance, state both sides and the conflict clearly. "
                "Do NOT resolve the conflict using outside knowledge or personal judgment.\n"
                "4. If the context lacks enough information to answer, respond with exactly: "
                "'The provided context does not contain enough information to answer this question.'\n\n"
                "Always structure your response in this exact format:\n"
                "Evidence:\n- [list every relevant fact from the context verbatim or as a close paraphrase]\n\n"
                "Reasoning:\n[step-by-step explanation using only the listed evidence]\n\n"
                "Answer:\n[final answer, one or two sentences]"
            ),
        ),
        ChatMessage(
            role=MessageRole.USER,
            content=(
                f"Context:\n{context}\n\n"
                f"Question: {request.query}\n\n"
                "Remember: use ONLY the context above. Do not add anything the context does not say."
            ),
        ),
    ]
"""


""" Failed
    messages = [
        ChatMessage(
            role=MessageRole.SYSTEM,
            content=(
                "You are a strict note-retrieval assistant. Your only source of truth is the context below. "
                "Follow every rule exactly:\n\n"
                "1. NEVER use knowledge from outside the provided context. If it is not in the context, it does not exist.\n"
                "2. Do NOT add, invent, or embellish any step, fact, or detail that is not explicitly stated in the context.\n"
                "If an item is listed in the context but its use is not described, do not invent a use for it."
                "3. If the context contains conflicting rules, identify the conflict. Use the specific/emergency guidance as an exception to the general/safety guidance."
                "If the context provides a priority (e.g., 'survival is the top priority'), follow that hierarchy. If no hierarchy exists, state that the rules are in direct conflict."
                "4. If the context lacks enough information to answer, respond with exactly: "
                "'The provided context does not contain enough information to answer this question.'\n\n"
                "Always structure your response in this exact format:\n"
                "Evidence:\n- [list every relevant fact from the context verbatim or as a close paraphrase]\n\n"
                "Reasoning:\n[step-by-step explanation using only the listed evidence]\n\n"
                "Answer:\n[final answer, one or two sentences]"
            ),
        ),
        ChatMessage(
            role=MessageRole.USER,
            content=(
                f"Context:\n{context}\n\n"
                f"Question: {request.query}\n\n"
                "Remember: use ONLY the context above. Do not add anything the context does not say."
            ),
        ),
    ]
"""