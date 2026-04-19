"""Intent exemplar management endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter

import structlog

from services.intent_service.intent import IntentStore, VALID_INTENTS

log = structlog.get_logger()

router = APIRouter(tags=["intent"])


class ExemplarItem(BaseModel):
    text: str = Field(..., min_length=3, max_length=500, example="What did I write about machine learning?")
    intent: str = Field(..., example="semantic")


class IngestExemplarsRequest(BaseModel):
    examples: list[ExemplarItem] = Field(..., min_length=1)
    source: str = Field("manual", example="production_log")


class IngestExemplarsResponse(BaseModel):
    ingested: int
    skipped_intents: list[str] = []


@router.post("/intent/exemplars", response_model=IngestExemplarsResponse)
def ingest_exemplars(request: IngestExemplarsRequest):
    """Ingest intent exemplars into the Qdrant intent collection.

    Accepts a list of ``{text, intent}`` pairs.  Unknown intents are
    skipped and reported in the response.
    """
    grouped: dict[str, list[str]] = {}
    skipped: set[str] = set()

    for ex in request.examples:
        if ex.intent not in VALID_INTENTS:
            skipped.add(ex.intent)
            continue
        grouped.setdefault(ex.intent, []).append(ex.text)

    if not grouped:
        return IngestExemplarsResponse(
            ingested=0,
            skipped_intents=sorted(skipped),
        )

    store = IntentStore()
    try:
        count = store.ingest(grouped, source=request.source)
    finally:
        store.close()

    log.info(
        "api.intent_exemplars_ingested",
        count=count,
        source=request.source,
        intents=list(grouped.keys()),
    )
    return IngestExemplarsResponse(
        ingested=count,
        skipped_intents=sorted(skipped),
    )
