from __future__ import annotations

from typing import Any, Callable

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import llm_call


def _stream_writer() -> Callable[[Any], None] | None:
    """Return LangGraph stream writer when finalizer streaming is active."""
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:  # noqa: BLE001
        return None


_MECHANICAL_PREFIXES = (
    "Here is what I found from tool results:",
    "Here is what I found:",
)


def _is_mechanical_text(text: str) -> bool:
    """Return whether text is a deterministic artifact dump."""
    return text.lstrip().startswith(_MECHANICAL_PREFIXES)


def finalizer_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    """Produce the final user-facing answer from an approved or mechanical draft."""
    # The finalizer is the last rendering pass. It preserves the approved
    # meaning and only spends another LLM call for mechanical artifact dumps.
    if state.get("pending_destructive"):
        return {}

    existing = str(state.get("final_answer") or state.get("draft_answer") or "").strip()

    # A router should only send terminal ("done") states here. Any other phase
    # is a routing bug; finalize defensively with an error instead of ending
    # the graph on an empty response.
    if state.get("phase") != "done":
        answer = existing or "I could not complete the request due to an unexpected workflow state."
        return {
            "phase": "done",
            "final_answer": answer,
            "error": state.get("error") or f"Workflow reached the finalizer in an unexpected phase: {state.get('phase')!r}.",
            "events": [
                {
                    "step": "finalizer.unexpected_phase",
                    "phase": str(state.get("phase") or ""),
                    "answer_chars": len(answer),
                }
            ],
        }

    if not existing:
        return {}
    if not config.policy.render_final_answer:
        return {"final_answer": existing, "events": [{"step": "finalizer.render_skipped", "reason": "disabled", "answer_chars": len(existing)}]}

    # An LLM-written draft is already user-facing prose; re-rendering it costs a
    # full LLM roundtrip for no quality gain. Render only mechanical drafts
    # (deterministic artifact dumps). Unknown provenance renders, conservatively.
    if state.get("draft_kind") == "llm" and not _is_mechanical_text(existing):
        final_answer = existing
        if config.policy.enforce_grounding:
            final_answer = _ensure_grounding(final_answer, state.get("artifacts") or [])
        return {
            "final_answer": final_answer,
            "events": [{"step": "finalizer.reused_draft", "draft_kind": "llm", "answer_chars": len(final_answer)}],
        }

    writer = _stream_writer()
    messages = _terminal_answer_messages(state, existing, config=config)
    finalizer_cfg = config.policy.finalizer

    def _render() -> str:
        """Helper for render."""
        with llm_call(
            node="finalizer",
            label="render_final_answer",
            messages=messages,
            max_tokens=finalizer_cfg.max_tokens,
        ):
            if writer is None:
                return llm.complete(messages, max_tokens=finalizer_cfg.max_tokens)
            parts: list[str] = []
            for token in llm.stream(messages, max_tokens=finalizer_cfg.max_tokens):
                if not token:
                    continue
                parts.append(token)
                writer({"type": "delta", "content": token})
            return "".join(parts)

    try:
        rendered = run_with_deadline(
            _render,
            timeout_seconds=config.policy.llm_timeout_seconds,
            label="final answer render LLM call",
        ).strip()
    except DeadlineExceeded:
        rendered = ""
    except Exception:  # noqa: BLE001
        rendered = ""

    final_answer = rendered or existing
    if config.policy.enforce_grounding:
        final_answer = _ensure_grounding(final_answer, state.get("artifacts") or [])
    return {
        "final_answer": final_answer,
        "events": [
            {
                "step": "finalizer.rendered",
                "used_llm_render": bool(rendered),
                "answer_chars": len(final_answer),
                "artifact_count": len(state.get("artifacts") or []),
            }
        ],
    }


def _terminal_answer_messages(state: AgentState, approved: str, *, config: AgentConfig) -> list[dict[str, str]]:
    """Build the finalizer prompt from the approved draft and artifacts."""
    finalizer_cfg = config.policy.finalizer
    artifacts = state.get("artifacts") or []
    source_lines = []
    for artifact in artifacts[: finalizer_cfg.max_artifact_lines]:
        source_ref = artifact.get("source_ref") or {}
        source_lines.append(
            f"- {artifact.get('tool', 'tool')}: {artifact.get('summary', '')} source_ref={source_ref}"[
                : finalizer_cfg.artifact_line_max_chars
            ]
        )

    return [
        {
            "role": "system",
            "content": (
                "You are the final answer renderer for an agent workflow. "
                "Write only the final user-facing answer. Preserve the approved meaning, "
                "use only the supplied draft and tool artifacts, do not add unsupported claims, "
                "and do not mention the review process."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User request:\n{state.get('user_query', '')}\n\n"
                f"Approved answer or best available draft:\n{approved}\n\n"
                f"Tool artifacts and source references:\n{chr(10).join(source_lines) if source_lines else '(none)'}\n\n"
                "Return only the answer text."
            ),
        },
    ]


def _ensure_grounding(answer: str, artifacts: list[dict[str, Any]]) -> str:
    """Append source references when grounding is required and missing."""
    if not artifacts:
        return answer
    refs = [_source_ref_text(artifact.get("source_ref") or {}) for artifact in artifacts[:3]]
    refs = [ref for ref in refs if ref]
    if not refs:
        return answer
    if any(ref in answer for ref in refs):
        return answer
    return f"{answer.rstrip()}\n\nSources: {', '.join(refs)}"


def _source_ref_text(source_ref: dict[str, Any]) -> str:
    """Format a compact source reference from artifact metadata."""
    parts = []
    for key in ("doc_id", "document_id", "page", "chunk_id", "id", "url", "title"):
        value = source_ref.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    return ";".join(parts)
