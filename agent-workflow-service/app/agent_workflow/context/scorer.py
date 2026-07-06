from __future__ import annotations

import hashlib
import math
import re
import time
from typing import Any

from app.agent_workflow.config import TruncationPolicy
from app.agent_workflow.state import Artifact


def score_artifact(
    *,
    summary: str,
    step_query: str,
    tool_result: Any,
    existing_artifacts: list[Artifact],
    policy: TruncationPolicy,
    semantic_score: float | None = None,
    created_at: float | None = None,
) -> dict[str, float]:
    """Score a tool artifact for relevance, freshness, uniqueness, and actionability."""
    relevance = _relevance_score(summary, step_query, semantic_score)
    freshness = _freshness_score(tool_result, created_at, policy.freshness_half_life_seconds)
    uniqueness = _uniqueness_score(summary, existing_artifacts)
    actionability = _actionability_score(tool_result)

    weights = policy.score_weights
    composite = (
        weights.get("relevance", 0.4) * relevance
        + weights.get("freshness", 0.2) * freshness
        + weights.get("uniqueness", 0.2) * uniqueness
        + weights.get("actionability", 0.2) * actionability
    )
    return {
        "relevance": round(relevance, 4),
        "freshness": round(freshness, 4),
        "uniqueness": round(uniqueness, 4),
        "actionability": round(actionability, 4),
        "composite": round(composite, 4),
    }


def _relevance_score(summary: str, step_query: str, semantic_score: float | None) -> float:
    """Compute the relevance score used for artifact ranking."""
    if semantic_score is not None:
        return max(0.0, min(float(semantic_score), 1.0))
    query_terms = set(_tokenize(step_query))
    if not query_terms:
        return 0.5
    summary_terms = set(_tokenize(summary))
    if not summary_terms:
        return 0.0
    overlap = len(query_terms & summary_terms) / len(query_terms)
    return max(0.0, min(overlap, 1.0))


def _freshness_score(
    tool_result: Any,
    created_at: float | None,
    half_life: float,
) -> float:
    """Compute the freshness score used for artifact ranking."""
    payload_time = _extract_timestamp(tool_result)
    reference = payload_time or created_at or time.time()
    age = max(0.0, time.time() - reference)
    if half_life <= 0:
        return 1.0
    return math.exp(-age / half_life)


def _uniqueness_score(summary: str, existing_artifacts: list[Artifact]) -> float:
    """Compute the uniqueness score used for artifact ranking."""
    if not existing_artifacts:
        return 1.0
    summary_tokens = set(_tokenize(summary))
    if not summary_tokens:
        return 0.5
    max_overlap = 0.0
    for artifact in existing_artifacts:
        prior_tokens = set(_tokenize(str(artifact.get("summary", ""))))
        if not prior_tokens:
            continue
        overlap = len(summary_tokens & prior_tokens) / len(summary_tokens | prior_tokens)
        max_overlap = max(max_overlap, overlap)
    return max(0.0, 1.0 - max_overlap)


def _actionability_score(tool_result: Any) -> float:
    """Compute the actionability score used for artifact ranking."""
    if isinstance(tool_result, dict):
        score = 0.2
        id_keys = ("id", "doc_id", "document_id", "card_id", "panel_id", "chunk_id")
        if any(key in tool_result for key in id_keys):
            score += 0.35
        if tool_result.get("ok") is True:
            score += 0.15
        rows = tool_result.get("rows") or tool_result.get("items") or tool_result.get("matches")
        if isinstance(rows, list) and rows:
            score += 0.2
        if any(k in tool_result for k in ("name", "title", "url", "uri", "path")):
            score += 0.1
        return min(score, 1.0)
    if isinstance(tool_result, list) and tool_result:
        return 0.6
    if isinstance(tool_result, str) and tool_result.strip():
        return 0.3
    return 0.1


def _extract_timestamp(tool_result: Any) -> float | None:
    """Extract timestamp from a larger payload."""
    if not isinstance(tool_result, dict):
        return None
    for key in ("updated_at", "modified_at", "timestamp", "version"):
        value = tool_result.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _tokenize(text: str) -> list[str]:
    """Helper for tokenize."""
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) > 1]


def content_fingerprint(text: str) -> str:
    """Build a stable fingerprint for text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
