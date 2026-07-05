from __future__ import annotations

from typing import Any, Callable

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState


def _stream_writer() -> Callable[[Any], None] | None:
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:  # noqa: BLE001
        return None


def finalizer_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    if state.get("phase") != "done" or state.get("pending_destructive"):
        return {}

    existing = str(state.get("final_answer") or state.get("draft_answer") or "").strip()
    if not existing:
        return {}
    if not config.policy.render_final_answer:
        return {"final_answer": existing}

    writer = _stream_writer()
    messages = _terminal_answer_messages(state, existing)

    def _render() -> str:
        if writer is None:
            return llm.complete(messages, max_tokens=2000)
        parts: list[str] = []
        for token in llm.stream(messages, max_tokens=2000):
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
    return {"final_answer": final_answer}


def _terminal_answer_messages(state: AgentState, approved: str) -> list[dict[str, str]]:
    artifacts = state.get("artifacts") or []
    source_lines = []
    for artifact in artifacts[:12]:
        source_ref = artifact.get("source_ref") or {}
        source_lines.append(
            f"- {artifact.get('tool', 'tool')}: {artifact.get('summary', '')} source_ref={source_ref}"[:1200]
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
    parts = []
    for key in ("doc_id", "document_id", "page", "chunk_id", "id", "url", "title"):
        value = source_ref.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    return ";".join(parts)
