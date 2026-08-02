import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import AGENT_API_KEY, AGENT_INTERNAL_URL
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.core.feature_flags import require_feature
from app.deps.auth import get_current_user
from app.logger import get_trace_id, logger
from app.schema.conversation import ChatStreamRequest


router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_feature("chat"))])


def _agent_payload(payload: ChatStreamRequest, current_user) -> dict:
    role_values = {getattr(role, "value", str(role)).lower() for role in current_user.role}
    agent_payload = payload.model_dump(mode="json", exclude_none=True)
    agent_payload.update({
        "user_id": str(current_user.id),
        "role": "admin" if role_values.intersection({"admin", "admin_user"}) else "user",
    })
    return agent_payload


_UPSTREAM_FAILURES = {
    401: ("Your session could not be verified. Please sign in again.", ErrorCode.UNAUTHORIZED),
    403: ("Your session could not be verified. Please sign in again.", ErrorCode.UNAUTHORIZED),
    422: ("That request could not be understood. Please rephrase and try again.", ErrorCode.VALIDATION_ERROR),
    429: ("Too many requests at once. Please wait a few seconds and try again.", ErrorCode.RATE_LIMITED),
    504: ("That took too long to answer. Please try again, or ask something narrower.", ErrorCode.MODEL_TIMEOUT),
}


def _upstream_failure(status: int) -> tuple[str, ErrorCode]:
    if status in _UPSTREAM_FAILURES:
        return _UPSTREAM_FAILURES[status]
    if 500 <= status <= 599:
        return (
            "The assistant is not reachable right now. Please try again in a moment.",
            ErrorCode.AGENT_UNAVAILABLE,
        )
    return ("Something went wrong on our end. Please try again.", ErrorCode.INTERNAL_ERROR)


async def _proxy_agent_stream(agent_payload: dict) -> StreamingResponse:
    headers = {"X-API-Key": AGENT_API_KEY}
    trace_id = get_trace_id()
    if trace_id:
        headers["X-Trace-Id"] = trace_id

    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5.0))
    try:
        request = client.build_request(
            "POST",
            f"{AGENT_INTERNAL_URL.rstrip('/')}/api/chat/stream",
            json=agent_payload,
            headers=headers,
        )
        response = await client.send(request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        # AppException so this leaves through the same envelope as every other
        # backend failure - the browser reads error.code, not prose.
        raise AppException(
            message="The assistant is not reachable right now. Please try again in a moment.",
            status_code=503,
            error_code=ErrorCode.AGENT_UNAVAILABLE,
        ) from exc

    if response.is_error:
        detail = await response.aread()
        status = response.status_code
        await response.aclose()
        await client.aclose()
        # Upstream body is for the logs; the client gets a code it can switch
        # on and copy it can show.
        message, code = _upstream_failure(status)
        logger.warning(
            "agent_upstream_error", status_code=status,
            detail=detail.decode(errors="replace")[:300],
        )
        raise AppException(message=message, status_code=status, error_code=code)

    async def iter_events():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        iter_events(),
        media_type=response.headers.get("content-type", "text/event-stream"),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stream", summary="Stream an authenticated RAG chat response")
async def stream_chat(
    payload: ChatStreamRequest,
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    """Authenticate the browser request and stream the trusted request through the agent."""
    return await _proxy_agent_stream(_agent_payload(payload, current_user))


@router.post(
    "/agent-stream",
    summary="Stream an authenticated agent-workflow chat response",
    dependencies=[Depends(require_feature("chat.agent_workflow"))],
)
async def stream_agent_chat(
    payload: ChatStreamRequest,
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    """Feature-flagged route for agent-workflow rollout through the Notelite agent."""
    return await _proxy_agent_stream(_agent_payload(payload, current_user))
