from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.dependencies import get_qdrant_store
from app.services.ingestion.actions.controller import PipelineActionController
from app.services.ingestion.actions.schema import PipelineActionRequest, PipelineActionResponse
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.schema import ApiResponse


router = APIRouter(prefix="/api/actions", tags=["pipeline-actions"])


@router.post(
    "/run",
    response_model=ApiResponse[PipelineActionResponse],
    summary="Run one ingestion or retrieval pipeline action",
    description=(
        "Runs exactly one typed pipeline action. Supported action_name values: "
        "ingestion.chunk, ingestion.keywords, ingestion.summary, ingestion.questions, "
        "ingestion.documents, retrieval.context, retrieval.prompt."
    ),
)
def run_pipeline_action(
    request: PipelineActionRequest,
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
):
    """Run a single typed pipeline stage for debugging and prompt/processor evaluation."""
    result = PipelineActionController(vector_store).run(request)
    return ApiResponse.ok(result)
