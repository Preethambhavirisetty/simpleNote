from __future__ import annotations

from typing import Any, TypedDict


class PlanStep(TypedDict, total=False):
    title: str
    action: str
    tool_hint: str
    expected_output: str
    stop_condition: str


class Plan(TypedDict, total=False):
    goal: str
    assumptions: list[str]
    risks: list[str]
    steps: list[PlanStep]
    acceptance_criteria: list[str]
    suggested_structure: str
    raw_markdown: str


class ReviewResult(TypedDict, total=False):
    verdict: str  # APPROVE | REVISE | REJECT
    scorecard: dict[str, Any]
    issues: list[str]
    missing_evidence: list[str]
    required_changes: list[str]
    approved_answer: str
    raw_markdown: str


class Artifact(TypedDict, total=False):
    id: str
    tool: str
    summary: str
    raw_ref: Any
    source_ref: dict[str, Any]
    scores: dict[str, float]
    composite_score: float
    created_at: float
    step_index: int
    truncated: bool


class ToolCallRecord(TypedDict, total=False):
    name: str
    args_preview: str
    status: str
    latency_ms: int
    error: str | None


class IterationCounters(TypedDict, total=False):
    executor_turns: int
    review_cycles: int
    tool_calls: int


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    user_query: str
    session_id: str
    runtime_context: dict[str, Any]
    plan: Plan
    current_step_index: int
    candidate_tools: list[dict[str, Any]]
    tool_discovery_cache: dict[str, list[dict[str, Any]]]
    artifacts: list[Artifact]
    tool_calls: list[ToolCallRecord]
    draft_answer: str
    review: ReviewResult
    review_feedback: str
    iteration: IterationCounters
    events: list[dict[str, Any]]
    phase: str
    final_answer: str
    error: str | None
    pending_destructive: dict[str, Any] | None
