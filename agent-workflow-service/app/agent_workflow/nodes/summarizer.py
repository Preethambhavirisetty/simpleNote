from __future__ import annotations

from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState, Artifact
from app.agent_workflow.telemetry import llm_call


def summarizer_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    """Compress accumulated artifacts into a running memo to free loop context.

    This runs mid-loop when retained artifacts approach the cap. It folds the
    lower-scoring artifacts into ``running_summary`` and drops them, keeping the
    top-scoring artifacts verbatim, then returns control to the executor so it
    has room to gather more evidence. Bounded by summary.max_cycles.
    """
    summary_cfg = config.policy.summary
    iteration = dict(state.get("iteration") or {})
    iteration["summaries"] = int(iteration.get("summaries") or 0) + 1

    artifacts = sorted(
        list(state.get("artifacts") or []),
        key=lambda artifact: float(artifact.get("composite_score") or 0.0),
        reverse=True,
    )
    # Always leave the trigger threshold clearable, even if keep is misconfigured
    # high, so compaction cannot livelock (max_cycles is the final backstop).
    keep_count = max(0, min(summary_cfg.keep_after_summary, summary_cfg.compact_after_artifacts - 1))
    keep = artifacts[:keep_count]
    folded = artifacts[keep_count:]

    if not folded:
        return {
            "iteration": iteration,
            "phase": "executing",
            "events": [{"step": "summarizer.noop", "reason": "nothing_to_compress", "summaries": iteration["summaries"]}],
        }

    existing = str(state.get("running_summary") or "").strip()
    messages = _messages(existing, folded)
    try:
        memo = run_with_deadline(
            lambda: _complete_summary(llm, messages, summary_cfg.max_tokens),
            timeout_seconds=config.policy.llm_timeout_seconds,
            label="summarizer LLM call",
        ).strip()
    except DeadlineExceeded as exc:
        memo = _fallback_memo(existing, folded)
        return {
            "running_summary": memo,
            "artifacts": keep,
            "iteration": iteration,
            "phase": "executing",
            "error": str(exc),
            "events": [{"step": "summarizer.timeout", "error": str(exc), "folded_count": len(folded)}],
        }

    memo = memo or _fallback_memo(existing, folded)
    return {
        "running_summary": memo,
        "artifacts": keep,
        "iteration": iteration,
        "phase": "executing",
        "events": [
            {
                "step": "summarizer.completed",
                "folded_count": len(folded),
                "kept_count": len(keep),
                "summaries": iteration["summaries"],
                "summary_chars": len(memo),
            }
        ],
    }


def _messages(existing: str, folded: list[Artifact]) -> list[dict[str, str]]:
    """Build the compaction prompt from prior memory and the folded artifacts."""
    findings = "\n".join(
        f"- [{artifact.get('tool', 'tool')}] {str(artifact.get('summary') or '').strip()}" for artifact in folded
    )
    return [
        {
            "role": "system",
            "content": (
                "You compress an agent's working memory during a tool-using task. "
                "Given prior memory and new tool findings, return an updated compact memo. "
                "Preserve names, ids, counts, and dates exactly. Do not invent details. "
                "Organize as short bullet lines under Confirmed facts, Open questions, and Dead ends. "
                "Return only the memo."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Prior memory:\n{existing or '(none)'}\n\n"
                f"New findings to fold in:\n{findings or '(none)'}\n\n"
                "Return the updated memo only."
            ),
        },
    ]


def _complete_summary(llm: LlmProvider, messages: list[dict[str, str]], max_tokens: int) -> str:
    """Run the summarizer LLM call inside the debug trace wrapper."""
    with llm_call(node="summarizer", label="compact_memory", messages=messages, max_tokens=max_tokens):
        return llm.complete(messages, max_tokens=max_tokens)


def _fallback_memo(existing: str, folded: list[Artifact]) -> str:
    """Deterministic memo when the LLM call is unavailable or empty."""
    lines = [existing] if existing else ["Confirmed facts:"]
    for artifact in folded:
        first = str(artifact.get("summary") or "").strip().splitlines()
        head = first[0] if first else ""
        if head:
            lines.append(f"- [{artifact.get('tool', 'tool')}] {head[:200]}")
    return "\n".join(lines).strip()
