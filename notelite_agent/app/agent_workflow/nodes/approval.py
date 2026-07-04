from __future__ import annotations

import json
from typing import Any, Callable

from langgraph.types import interrupt

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.nodes.executor import _record_denial, _run_tool_and_record
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.state import AgentState, Artifact


def approval_node(
    state: AgentState,
    *,
    config: AgentConfig,
    tools: ToolProvider,
    on_tool_call: Callable[[str, dict[str, Any], Any], None] | None = None,
    on_artifact: Callable[[Artifact], None] | None = None,
) -> dict[str, Any]:
    """Human-in-the-loop gate for destructive tool calls.

    Pauses the graph at a checkpoint via ``interrupt`` and resumes with the
    host's decision (``Command(resume={"approved": bool})``). This node holds no
    LLM call: on resume LangGraph re-executes the node from the top, so keeping
    it side-effect-free before the interrupt makes replay cheap and
    deterministic. The tool executes only after an explicit approval.
    """
    pending = dict(state.get("pending_destructive") or {})
    tool_name = str(pending.get("tool") or "")
    arguments = pending.get("arguments") if isinstance(pending.get("arguments"), dict) else {}

    decision = interrupt(
        {
            "type": "destructive_approval",
            "tool": tool_name,
            "arguments_preview": json.dumps(arguments)[:500],
            "step_index": pending.get("step_index"),
        }
    )
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)

    updates: dict[str, Any] = {
        "pending_destructive": None,
        "phase": "executing",
        "events": [{"step": "approval.approved" if approved else "approval.denied", "tool": tool_name}],
    }
    if not approved:
        _record_denial(state, updates, tool_name, arguments)
        return updates

    return _run_tool_and_record(
        state=state,
        config=config,
        tools=tools,
        tool_name=tool_name,
        arguments=arguments,
        updates=updates,
        iteration=dict(state.get("iteration") or {}),
        step_index=int(pending.get("step_index") or 0),
        step_query=str(pending.get("step_query") or ""),
        on_tool_call=on_tool_call,
        on_artifact=on_artifact,
    )
