from __future__ import annotations

from pathlib import Path

from app.agent_workflow.config import load_agent_config
from app.agent_workflow.nodes.executor import executor_node
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider


class CallToolLlm(LlmProvider):
    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return self.payload

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.payload


class RecordingTools(ToolProvider):
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"ok": True}


def _state(runtime_context: dict | None = None) -> dict:
    return {
        "user_query": "Find docs",
        "phase": "executing",
        "iteration": {},
        "current_step_index": 0,
        "runtime_context": runtime_context or {},
        "plan": {
            "goal": "Find docs",
            "steps": [{"title": "Search", "action": "search", "tool_hint": "search_documents"}],
        },
        "candidate_tools": [
            {
                "name": "search_documents",
                "title": "Search Documents",
                "description": "Search docs",
                "score": 0.9,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "tenant_id": {"type": "string"},
                    },
                    "required": ["query", "tenant_id"],
                    "additionalProperties": False,
                },
            }
        ],
        "tool_calls": [],
        "artifacts": [],
    }


def test_runtime_argument_injection_populates_required_tool_args():
    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    config.policy.tools.argument_injection = {"search_documents": {"tenant_id": "tenant.id"}}
    tools = RecordingTools()
    updates = executor_node(
        _state(runtime_context={"tenant": {"id": "t-123"}}),
        config=config,
        llm=CallToolLlm('{"action":"call_tool","name":"search_documents","arguments":{"query":"SLA"}}'),
        tools=tools,
    )
    assert tools.calls == [("search_documents", {"query": "SLA", "tenant_id": "t-123"})]
    assert updates["tool_calls"][-1]["status"] == "ok"


def test_tool_denylist_blocks_call_execution():
    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    config.policy.tools.denylist = ["search_documents"]
    tools = RecordingTools()
    updates = executor_node(
        _state(),
        config=config,
        llm=CallToolLlm('{"action":"call_tool","name":"search_documents","arguments":{"query":"SLA"}}'),
        tools=tools,
    )
    assert tools.calls == []
    assert updates["tool_calls"][-1]["status"] == "invalid_args"
    assert "blocked by policy" in (updates["tool_calls"][-1]["error"] or "")
