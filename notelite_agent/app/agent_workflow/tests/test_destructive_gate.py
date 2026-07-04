"""Fail-closed destructive gate + checkpointed approval flow.

The invariant under test: a tool listed in policy.destructive_tools NEVER
executes without an explicit approval — either a synchronous host callback or
an out-of-band resume of the checkpointed interrupt. Absence of an approver
must pause the run, not execute the tool.
"""
from __future__ import annotations

from pathlib import Path

from app.agent_workflow.config import load_agent_config
from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider
from app.agent_workflow.streaming import HostCallbacks, RunRequest


CONFIG_PATH = Path(__file__).resolve().parents[1] / "agents" / "document.yaml"

PLAN = (
    "### Goal\nDelete the obsolete doc\n### Assumptions\nNone\n### Risks and edge cases\nNone\n"
    "### Execution plan\n1. **Delete** — Action: delete the doc — Tool hint: delete_document\n"
    "### Acceptance criteria\n- Doc deleted\n### Suggested user-facing structure\nSummary"
)
CALL_DELETE = '{"action":"call_tool","name":"delete_document","arguments":{"doc_id":"d1"}}'
DRAFT = '{"action":"draft_answer","answer":"Handled the deletion request."}'
APPROVE_REVIEW = (
    "### Verdict\nAPPROVE\n### Issues found\nNone\n### Missing evidence\nNone\n"
    "### Required changes\nNone\n### Approved answer\nHandled the deletion request."
)


class RecordingTools(ToolProvider):
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"ok": True, "doc_id": arguments.get("doc_id"), "deleted": True}


class ScriptedLlm(LlmProvider):
    """Returns scripted responses in order; repeats the last one when exhausted."""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = 0

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def make_engine(responses: list[str], **callback_kwargs) -> tuple[AgentEngine, RecordingTools]:
    tools = RecordingTools()
    engine = AgentEngine(
        config=load_agent_config(CONFIG_PATH),
        llm=ScriptedLlm(responses),
        tools=tools,
        callbacks=HostCallbacks(**callback_kwargs),
    )
    return engine, tools


def test_no_approver_pauses_without_executing():
    engine, tools = make_engine([PLAN, CALL_DELETE, DRAFT, APPROVE_REVIEW])

    result = engine.run(RunRequest(query="Delete doc d1"))

    assert tools.calls == []  # fail closed: never executed
    assert result.pending_approval is not None
    assert result.pending_approval["tool"] == "delete_document"
    assert result.thread_id
    assert result.error is None
    assert "approval" in result.answer.lower()


def test_resume_approved_executes_and_completes():
    engine, tools = make_engine([PLAN, CALL_DELETE, DRAFT, APPROVE_REVIEW])
    paused = engine.run(RunRequest(query="Delete doc d1"))
    assert tools.calls == []

    result = engine.resume(paused.thread_id, approved=True)

    assert tools.calls == [("delete_document", {"doc_id": "d1"})]  # exactly once
    assert result.pending_approval is None
    assert result.review.get("verdict") == "APPROVE"
    assert "deletion" in result.answer.lower()
    assert any(record.get("name") == "delete_document" and record.get("status") == "ok"
               for record in result.tool_calls)


def test_resume_denied_skips_and_still_completes():
    # After the denial the LLM asks for the same tool again — the gate must
    # skip it (previously denied) instead of pausing in a loop.
    engine, tools = make_engine([PLAN, CALL_DELETE, CALL_DELETE, DRAFT, APPROVE_REVIEW])
    paused = engine.run(RunRequest(query="Delete doc d1"))

    result = engine.resume(paused.thread_id, approved=False)

    assert tools.calls == []  # never executed
    assert result.pending_approval is None
    assert result.review.get("verdict") == "APPROVE"
    assert any(record.get("status") == "denied" for record in result.tool_calls)


def test_sync_callback_approval_executes_inline():
    asked: list[str] = []

    def approver(tool: str, arguments: dict) -> bool:
        asked.append(tool)
        return True

    engine, tools = make_engine(
        [PLAN, CALL_DELETE, DRAFT, APPROVE_REVIEW], on_destructive_action=approver
    )
    result = engine.run(RunRequest(query="Delete doc d1"))

    assert asked == ["delete_document"]
    assert tools.calls == [("delete_document", {"doc_id": "d1"})]
    assert result.pending_approval is None
    assert result.review.get("verdict") == "APPROVE"


def test_sync_callback_denial_blocks_execution():
    engine, tools = make_engine(
        [PLAN, CALL_DELETE, CALL_DELETE, DRAFT, APPROVE_REVIEW],
        on_destructive_action=lambda tool, arguments: False,
    )
    result = engine.run(RunRequest(query="Delete doc d1"))

    assert tools.calls == []
    assert result.pending_approval is None
    assert any(record.get("status") == "denied" for record in result.tool_calls)
    assert result.review.get("verdict") == "APPROVE"


def test_stream_emits_pending_approval_event():
    engine, tools = make_engine([PLAN, CALL_DELETE, DRAFT, APPROVE_REVIEW])

    events = list(engine.stream(RunRequest(query="Delete doc d1")))

    pending = [e for e in events if e.get("type") == "pending_approval"]
    assert len(pending) == 1
    assert pending[0]["tool"] == "delete_document"
    assert pending[0]["thread_id"]
    done = [e for e in events if e.get("type") == "done"]
    assert done and done[-1].get("pending_approval")
    assert tools.calls == []


def test_resume_unknown_thread_reports_error():
    engine, _tools = make_engine([PLAN, CALL_DELETE, DRAFT, APPROVE_REVIEW])
    result = engine.resume("no-such-thread", approved=True)
    assert result.error


def test_graph_compiled_once_across_runs():
    engine, _tools = make_engine(
        [PLAN, DRAFT, APPROVE_REVIEW],  # no tool call: plan -> draft -> approve
    )
    graph_before = engine.graph
    engine.run(RunRequest(query="q1"))
    engine.run(RunRequest(query="q2"))
    assert engine.graph is graph_before
