"""Retrieval endpoints — context lookup and non-streaming chat."""

import logging

from fastapi import APIRouter

from apis.schema import RetrieveRequest
from core.contracts import AccessContext
from services.retrieval import VectorStore
from llama_index.core import Settings
from llama_index.core.llms import ChatMessage, MessageRole

log = logging.getLogger(__name__)

router = APIRouter(tags=["retrieval"])


@router.post("/get-context")
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


@router.post("/chat")
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
