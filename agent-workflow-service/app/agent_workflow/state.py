from __future__ import annotations

from typing import Any, TypedDict


class PlanStep(TypedDict, total=False):
    """One planner step with optional tool and stopping guidance."""
    title: str
    action: str
    tool_hint: str
    expected_output: str
    stop_condition: str
    required_tools: list[str]


class Plan(TypedDict, total=False):
    """Structured planner output shared with executor and reviewer nodes."""
    goal: str
    assumptions: list[str]
    risks: list[str]
    steps: list[PlanStep]
    acceptance_criteria: list[str]
    suggested_structure: str
    raw_markdown: str


class ReviewResult(TypedDict, total=False):
    """Structured reviewer verdict and requested changes."""
    verdict: str  # APPROVE | REVISE | REJECT
    scorecard: dict[str, Any]
    issues: list[str]
    missing_evidence: list[str]
    required_changes: list[str]
    approved_answer: str
    raw_markdown: str


class Artifact(TypedDict, total=False):
    """Normalized evidence captured from a tool call."""
    id: str
    tool: str
    summary: str
    raw_ref: Any
    source_ref: dict[str, Any]
    scores: dict[str, float]
    composite_score: float
    created_at: float
    step_index: int
    replan_id: int
    truncated: bool


class Fact(TypedDict, total=False):
    """Compact claim extracted from artifacts for synthesis and review."""
    id: str
    text: str
    source_artifact_id: str
    tool: str
    source_ref: dict[str, Any]
    confidence: float
    truncated_source: bool


class ToolCallRecord(TypedDict, total=False):
    """Compact audit record for one attempted tool call."""
    name: str
    args_preview: str
    status: str
    latency_ms: int
    error: str | None


class IterationCounters(TypedDict, total=False):
    """Counters used to cap loops and review cycles."""
    executor_turns: int
    review_cycles: int
    revision_cycles: int
    tool_calls: int
    replans: int


class AgentState(TypedDict, total=False):
    """LangGraph state object passed between workflow nodes."""
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
    facts: list[Fact]
    draft_answer: str
    draft_kind: str  # "mechanical" (deterministic artifact dump) | "llm" (prose) | "executor_draft" (raw executor answer)
    review: ReviewResult
    review_feedback: str
    iteration: IterationCounters
    events: list[dict[str, Any]]
    phase: str
    final_answer: str
    error: str | None
    pending_destructive: dict[str, Any] | None
