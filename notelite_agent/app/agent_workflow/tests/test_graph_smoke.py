from __future__ import annotations

from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider
from app.agent_workflow.streaming import HostCallbacks, RunRequest


class MockTools(ToolProvider):
    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        return [
            ToolCandidate(
                name="search_documents",
                title="Search Documents",
                description="Search docs",
                score=0.9,
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ]

    def call_tool(self, name: str, arguments: dict) -> dict:
        return {
            "ok": True,
            "doc_id": "doc-1",
            "page": 2,
            "items": [{"text": "SLA requirement", "chunk_id": "c1"}],
        }


class MockLlm(LlmProvider):
    def __init__(self):
        self.calls = 0

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        self.calls += 1
        if self.calls == 1:
            return (
                "### Goal\nFind SLA\n### Assumptions\nNone\n### Risks and edge cases\nNone\n"
                "### Execution plan\n1. **Search** — Action: search — Tool hint: search_documents\n"
                "### Acceptance criteria\n- SLA found\n### Suggested user-facing structure\nSummary"
            )
        if self.calls == 2:
            return '{"action":"search_tools","query":"SLA documents"}'
        if self.calls == 3:
            return '{"action":"finish_step"}'
        if self.calls == 4:
            return '{"action":"draft_answer","answer":"Found SLA in doc-1 page 2."}'
        return (
            "### Verdict\nAPPROVE\n### Issues found\nNone\n### Missing evidence\nNone\n"
            "### Required changes\nNone\n### Approved answer\nFound SLA in doc-1 page 2."
        )

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def test_graph_smoke_approve_path():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    engine = AgentEngine(config=config, llm=MockLlm(), tools=MockTools(), callbacks=HostCallbacks())
    result = engine.run(RunRequest(query="Find SLA mentions"))
    assert "SLA" in result.answer
    assert result.review.get("verdict") == "APPROVE"
    assert result.artifacts
