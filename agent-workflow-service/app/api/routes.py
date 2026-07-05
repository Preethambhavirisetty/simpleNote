from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.api_response import ApiResponse
from app.api.dependencies import require_api_key
from app.api.runtime import (
    build_run_request,
    resolve_engine,
    resolve_engine_from_runtime_bundle,
    stream_sse,
    stream_sse_runtime_bundle,
)
from app.api.schema import (
    AgentWorkflowResumeRequest,
    AgentWorkflowRunRequest,
    AgentWorkflowRuntimeBundleRequest,
)


router = APIRouter(
    prefix="/api/agent-workflow",
    tags=["agent-workflow"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/run", response_model=ApiResponse[dict])
def run_agent_workflow(payload: AgentWorkflowRunRequest):
    engine = resolve_engine(payload)
    result = engine.run(build_run_request(payload))
    return ApiResponse.ok(
        {
            "thread_id": result.thread_id,
            "answer": result.answer,
            "review": result.review,
            "artifact_count": len(result.artifacts),
            "tool_call_count": len(result.tool_calls),
            "pending_approval": result.pending_approval,
            "error": result.error,
        }
    )


@router.post("/run/runtime-bundle", response_model=ApiResponse[dict])
def run_agent_workflow_runtime_bundle(payload: AgentWorkflowRuntimeBundleRequest):
    engine = resolve_engine_from_runtime_bundle(payload)
    result = engine.run(build_run_request(payload))
    return ApiResponse.ok(
        {
            "thread_id": result.thread_id,
            "answer": result.answer,
            "review": result.review,
            "artifact_count": len(result.artifacts),
            "tool_call_count": len(result.tool_calls),
            "pending_approval": result.pending_approval,
            "error": result.error,
        }
    )


@router.post("/stream")
def stream_agent_workflow(payload: AgentWorkflowRunRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_sse(payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/stream/runtime-bundle")
def stream_agent_workflow_runtime_bundle(payload: AgentWorkflowRuntimeBundleRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_sse_runtime_bundle(payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume", response_model=ApiResponse[dict])
def resume_agent_workflow(payload: AgentWorkflowResumeRequest):
    engine = resolve_engine(
        AgentWorkflowRunRequest(
            query="resume",
            session_id=payload.thread_id,
            config_name=payload.config_name,
            config_path=payload.config_path,
            config=payload.config,
            runtime_overrides=payload.runtime_overrides,
        )
    )
    result = engine.resume(payload.thread_id, approved=payload.approved)
    return ApiResponse.ok(
        {
            "thread_id": result.thread_id,
            "answer": result.answer,
            "review": result.review,
            "artifact_count": len(result.artifacts),
            "tool_call_count": len(result.tool_calls),
            "pending_approval": result.pending_approval,
            "error": result.error,
        }
    )
