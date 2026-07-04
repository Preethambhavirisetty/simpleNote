from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.schema.responses import ApiResponse, ConversationData, ConversationDetailData, MessageData

from app.core.feature_flags import require_feature
from app.db.postgres.models.conversation import Conversation, Message
from app.db.postgres.session import get_postgres_session
from app.deps.auth import get_current_user
from app.deps.internal import verify_internal_key
from app.exceptions.base import AppException
from app.exceptions.handlers import success_response
from app.schema.base import ErrorCode
from app.schema.conversation import ConversationCreate, MessageCreate, MessageUpdate
from app.services.conversations import ConversationService

router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
    dependencies=[Depends(require_feature("chat"))],
)


def get_conversation_service():
    return ConversationService()


def _resolve_user_id(
    current_user=None,
    x_user_id: Optional[str] = None,
    x_internal_key: Optional[str] = None,
) -> UUID:
    """Return user_id from JWT user or from agent service header."""
    if current_user:
        return current_user.id
    if x_internal_key and x_user_id:
        verify_internal_key(x_internal_key)
        return UUID(x_user_id)
    raise AppException(
        message="Authentication required",
        status_code=401,
        error_code=ErrorCode.NOT_AUTHENTICATED,
    )


def _conv_dict(conv: Conversation) -> dict:
    return {
        "id": str(conv.id),
        "user_id": str(conv.user_id),
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
    }


def _conv_detail_dict(conv: Conversation) -> dict:
    d = _conv_dict(conv)
    d["messages"] = [_msg_dict(m) for m in conv.messages]
    return d


def _msg_dict(msg: Message) -> dict:
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "role": msg.role,
        "content": msg.content,
        "status": msg.status,
        "model_used": msg.model_used,
        "latency_ms": msg.latency_ms,
        "tokens_used": msg.tokens_used,
        "sources_used": msg.sources_used,
        "error_message": msg.error_message,
        "created_at": msg.created_at.isoformat(),
    }


# ── Cookie-auth routes (FE) ──────────────────────────────────────────────────

@router.get("/", response_model=ApiResponse[list[ConversationData]], summary="List conversations")
def list_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: ConversationService = Depends(get_conversation_service),
):
    """List conversations owned by the authenticated user."""
    convs = service.list(db, current_user.id, skip=skip, limit=limit)
    return success_response([_conv_dict(c) for c in convs], "Conversations retrieved")


@router.post("/", response_model=ApiResponse[ConversationData], summary="Create a conversation")
def create_conversation(
    payload: ConversationCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: ConversationService = Depends(get_conversation_service),
):
    """Create a conversation for the authenticated user."""
    conv = service.create(db, current_user.id, payload)
    return success_response(_conv_dict(conv), "Conversation created")


@router.get("/{conv_id}", response_model=ApiResponse[ConversationDetailData], summary="Get a conversation")
def get_conversation(
    conv_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: ConversationService = Depends(get_conversation_service),
):
    """Return one conversation and its messages."""
    conv = service.get(db, conv_id, current_user.id)
    return success_response(_conv_detail_dict(conv), "Conversation retrieved")


@router.delete("/{conv_id}", response_model=ApiResponse[None], summary="Delete a conversation")
def delete_conversation(
    conv_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: ConversationService = Depends(get_conversation_service),
):
    """Delete one conversation owned by the authenticated user."""
    service.delete(db, conv_id, current_user.id)
    return success_response(None, "Conversation deleted")


# ── Internal service routes (Agent -> Backend) ────────────────────────────────
# These use X-Internal-Key + X-User-Id headers instead of cookies.

@router.get("/internal/{conv_id}", response_model=ApiResponse[ConversationDetailData], summary="Get a conversation internally")
def internal_get_conversation(
    conv_id: UUID,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: ConversationService = Depends(get_conversation_service),
):
    """Return one conversation for an authenticated internal agent request."""
    user_id = _resolve_user_id(x_internal_key=x_internal_key, x_user_id=x_user_id)
    conv = service.get(db, conv_id, user_id)
    return success_response(_conv_detail_dict(conv), "Conversation retrieved")


@router.post("/internal/", response_model=ApiResponse[ConversationData], summary="Create a conversation internally")
def internal_create_conversation(
    payload: ConversationCreate,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: ConversationService = Depends(get_conversation_service),
):
    """Create a conversation for an authenticated internal agent request."""
    user_id = _resolve_user_id(x_internal_key=x_internal_key, x_user_id=x_user_id)
    conv = service.create(db, user_id, payload)
    return success_response(_conv_dict(conv), "Conversation created")


@router.post("/internal/{conv_id}/messages", response_model=ApiResponse[MessageData], summary="Create a conversation message internally")
def internal_create_message(
    conv_id: UUID,
    payload: MessageCreate,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: ConversationService = Depends(get_conversation_service),
):
    """Create a message in a conversation from the agent service."""
    user_id = _resolve_user_id(x_internal_key=x_internal_key, x_user_id=x_user_id)
    msg = service.create_message(db, conv_id, user_id, payload)
    return success_response(_msg_dict(msg), "Message created")


@router.patch("/internal/{conv_id}/messages/{msg_id}", response_model=ApiResponse[MessageData], summary="Update a conversation message internally")
def internal_update_message(
    conv_id: UUID,
    msg_id: UUID,
    payload: MessageUpdate,
    x_internal_key: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_postgres_session),
    service: ConversationService = Depends(get_conversation_service),
):
    """Update a conversation message from the agent service."""
    user_id = _resolve_user_id(x_internal_key=x_internal_key, x_user_id=x_user_id)
    msg = service.update_message(db, conv_id, msg_id, user_id, payload)
    return success_response(_msg_dict(msg), "Message updated")
