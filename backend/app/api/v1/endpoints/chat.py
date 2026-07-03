import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import AGENT_API_KEY, AGENT_INTERNAL_URL
from app.core.feature_flags import require_feature
from app.deps.auth import get_current_user
from app.schema.conversation import ChatStreamRequest


router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_feature("chat"))])


@router.post("/stream", summary="Stream an authenticated RAG chat response")
async def stream_chat(
    payload: ChatStreamRequest,
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    """Authenticate the browser request and stream the trusted request through the agent."""
    role_values = {getattr(role, "value", str(role)).lower() for role in current_user.role}
    agent_payload = payload.model_dump(mode="json", exclude_none=True)
    agent_payload.update({
        "user_id": str(current_user.id),
        "role": "admin" if role_values.intersection({"admin", "admin_user"}) else "user",
    })

    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5.0))
    try:
        request = client.build_request(
            "POST",
            f"{AGENT_INTERNAL_URL.rstrip('/')}/api/chat/stream",
            json=agent_payload,
            headers={"X-API-Key": AGENT_API_KEY},
        )
        response = await client.send(request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(status_code=503, detail="Agent service unavailable") from exc

    if response.is_error:
        detail = await response.aread()
        await response.aclose()
        await client.aclose()
        raise HTTPException(
            status_code=response.status_code,
            detail=detail.decode(errors="replace") or "Agent request failed",
        )

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
