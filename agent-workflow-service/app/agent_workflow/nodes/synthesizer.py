from __future__ import annotations

from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.prompts.output_markdown import MARKDOWN_OUTPUT_RULES
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import llm_call


def synthesizer_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    """Write the main draft answer from compact facts only."""
    # The synthesizer is the single normal authoring pass. It consumes compact
    # facts so reviewer/revision do not have to carry giant raw tool output.
    facts = list(state.get("facts") or [])
    if not facts and state.get("draft_answer"):
        draft = str(state.get("draft_answer") or "").strip()
        result = _done_or_reviewing(state, config, draft, "executor_draft", skipped_reason="no_facts")
        result["events"] = [{"step": "synthesizer.skipped", "reason": "no_facts_executor_draft", "answer_chars": len(draft)}]
        return result
    if not facts:
        draft = _fallback_from_state(state)
        result = _done_or_reviewing(state, config, draft, "mechanical", skipped_reason="no_facts")
        result["events"] = [{"step": "synthesizer.fallback", "reason": "no_facts", "answer_chars": len(draft)}]
        return result

    messages = _messages(state, config=config)
    try:
        draft = run_with_deadline(
            lambda: _complete_synthesis(llm, messages, config.policy.executor.synthesize_max_tokens),
            timeout_seconds=config.policy.llm_timeout_seconds,
            label="synthesizer LLM call",
        ).strip()
    except DeadlineExceeded as exc:
        draft = _fallback_from_facts(facts)
        result = _done_or_reviewing(state, config, draft, "mechanical", skipped_reason="synthesis_timeout")
        result["error"] = str(exc)
        result["events"] = [{"step": "synthesizer.timeout", "error": str(exc), "fact_count": len(facts), "answer_chars": len(draft)}]
        return result

    if not draft:
        draft = _fallback_from_facts(facts)
        result = _done_or_reviewing(state, config, draft, "mechanical", skipped_reason="empty_synthesis")
        result["events"] = [{"step": "synthesizer.fallback", "reason": "empty_synthesis", "fact_count": len(facts), "answer_chars": len(draft)}]
        return result

    result = _done_or_reviewing(state, config, draft, "llm")
    result["events"] = [{"step": "synthesizer.completed", "fact_count": len(facts), "answer_chars": len(result.get("draft_answer", ""))}]
    return result


def _done_or_reviewing(
    state: AgentState,
    config: AgentConfig,
    draft: str,
    draft_kind: str,
    *,
    skipped_reason: str = "reviewer_disabled",
) -> dict[str, Any]:
    """Route the draft to reviewer or directly to finalization based on policy."""
    reviewer_enabled = config.policy.enable_reviewer and config.policy.reviewer.enabled
    if reviewer_enabled and config.policy.reviewer.mode == "on_risk" and not _run_has_risk(state):
        reviewer_enabled = False
        skipped_reason = "reviewer_not_required"
    updates: dict[str, Any] = {"draft_answer": draft, "draft_kind": draft_kind}
    if reviewer_enabled:
        updates["phase"] = "reviewing"
    else:
        updates["phase"] = "done"
        updates["final_answer"] = draft
        updates["review"] = {"verdict": "SKIPPED", "reason": skipped_reason}
    return updates


def _run_has_risk(state: AgentState) -> bool:
    """Return whether deterministic signals justify a reviewer call."""
    if state.get("error"):
        return True
    return any(str(record.get("status") or "") != "ok" for record in state.get("tool_calls") or [])


def _messages(state: AgentState, *, config: AgentConfig) -> list[dict[str, str]]:
    """Build a synthesis prompt from primary evidence, facts, plan, and request."""
    fact_lines = []
    for idx, fact in enumerate(state.get("facts") or [], start=1):
        source = fact.get("source_ref") or {}
        source_text = f" source={source}" if source else ""
        fact_lines.append(f"{idx}. {fact.get('text', '')} [tool={fact.get('tool', '')}; id={fact.get('id', '')}{source_text}]")
    evidence = _primary_evidence(state, config=config)
    plan = state.get("plan") or {}
    criteria = "\n".join(f"- {item}" for item in plan.get("acceptance_criteria") or [])
    history_block = _follow_up_history_block(state, config=config)
    user_content = (
        f"User request:\n{state.get('user_query', '')}\n\n"
        f"Goal:\n{plan.get('goal', '')}\n\n"
        f"Acceptance criteria:\n{criteria or '(none)'}\n\n"
        f"Primary evidence (verbatim tool results, highest-scored first):\n{evidence or '(none)'}\n\n"
        f"Facts with provenance:\n{chr(10).join(fact_lines) if fact_lines else '(none)'}\n\n"
        "Return only the draft answer in GFM markdown."
    )
    if history_block:
        user_content = f"{history_block}\n\n{user_content}"
    return [
        {
            "role": "system",
            "content": (
                "You are the synthesizer node in a tool workflow. Write one clear final-answer draft. "
                "Ground the answer in the primary evidence (verbatim tool results) below; the compact facts "
                "are a provenance index over that evidence. Do not invent details beyond it, and do not "
                "mention internal nodes, review, or hidden policy. If evidence is incomplete, say what is "
                "unavailable.\n\n"
                f"{MARKDOWN_OUTPUT_RULES}"
            ),
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def _follow_up_history_block(state: AgentState, *, config: AgentConfig) -> str:
    """Bounded prior-turn context for formatting/clarification follow-ups."""
    runtime = state.get("runtime_context") if isinstance(state.get("runtime_context"), dict) else {}
    if not runtime.get("follow_up"):
        return ""
    messages = state.get("messages") or []
    if not messages:
        return ""
    limit = min(4, int(config.policy.context.max_history_messages))
    if limit <= 0:
        # messages[-0:] would leak the entire history; 0 means "no history".
        return ""
    lines: list[str] = []
    for message in messages[-limit:]:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        preview = content[:1200] + ("…" if len(content) > 1200 else "")
        lines.append(f"{role}: {preview}")
    if not lines:
        return ""
    return "Prior conversation (for follow-up formatting/context only):\n" + "\n".join(lines)


def _primary_evidence(state: AgentState, *, config: AgentConfig) -> str:
    """Top artifact summaries verbatim so a single rich result is not lost to fact compression.

    Bounded by a char budget (~a third of the context window) so it complements,
    not overflows, the compact facts — for one rich result the whole summary is
    included; for many, the highest-scoring few are, and facts cover the tail.
    """
    artifacts = sorted(
        state.get("artifacts") or [],
        key=lambda artifact: float(artifact.get("composite_score") or 0.0),
        reverse=True,
    )
    budget = max(4000, int(config.policy.max_context_tokens))
    blocks: list[str] = []
    used = 0
    for artifact in artifacts:
        summary = str(artifact.get("summary") or "").strip()
        if not summary:
            continue
        source = artifact.get("source_ref") or {}
        header = f"- [{artifact.get('tool', 'tool')}]" + (f" source={source}" if source else "")
        block = f"{header}\n{summary}"
        if used + len(block) > budget and blocks:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _complete_synthesis(llm: LlmProvider, messages: list[dict[str, str]], max_tokens: int) -> str:
    """Run the synthesis LLM call inside the debug trace wrapper."""
    with llm_call(node="synthesizer", label="write_answer", messages=messages, max_tokens=max_tokens):
        return llm.complete(messages, max_tokens=max_tokens)


def _fallback_from_state(state: AgentState) -> str:
    """Return a useful answer when no facts were extracted."""
    if state.get("error"):
        return f"I could not complete the request: {state.get('error')}"
    return "I completed the available workflow steps, but I do not have enough evidence to provide a detailed answer."


def _fallback_from_facts(facts: list[dict[str, Any]]) -> str:
    """Render a deterministic answer directly from compact facts."""
    lines = ["## Results", ""]
    for fact in facts[:12]:
        lines.append(f"- {fact.get('text', '')}")
    return "\n".join(lines)
