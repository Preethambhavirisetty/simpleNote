from __future__ import annotations

from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider
from app.agent_workflow.streaming import HostCallbacks, RunRequest


class MockTools(ToolProvider):
    def __init__(self):
        self.searches: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        self.searches.append(query)
        return [
            ToolCandidate(
                name="search_documents",
                title="Search Documents",
                description="Search docs",
                score=0.9,
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            )
        ]

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
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
            return '{"action":"call_tool","name":"search_documents","arguments":{"query":"SLA documents"}}'
        if self.calls == 4:
            return '{"action":"finish_step"}'
        if self.calls == 5:
            return '{"action":"draft_answer","answer":"Found SLA in doc-1 page 2."}'
        return (
            "### Verdict\nAPPROVE\n### Issues found\nNone\n### Missing evidence\nNone\n"
            "### Required changes\nNone\n### Approved answer\nFound SLA in doc-1 page 2."
        )

    def stream(self, messages, *, max_tokens: int = 1024):
        yield "Found "
        yield "SLA in doc-1 page 2."


class DirectLlm(LlmProvider):
    def __init__(self):
        self.complete_calls = 0
        self.stream_calls = 0

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        self.complete_calls += 1
        return "4"

    def stream(self, messages, *, max_tokens: int = 1024):
        self.stream_calls += 1
        yield "4"


def test_fast_path_answers_simple_query_without_tools_or_graph_loop():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    llm = DirectLlm()
    tools = MockTools()
    engine = AgentEngine(config=config, llm=llm, tools=tools, callbacks=HostCallbacks())

    result = engine.run(RunRequest(query="What is 2+2?"))

    assert result.answer == "4"
    assert result.review.get("verdict") == "SKIPPED"
    assert result.events[-1]["step"] == "router.fast_path"
    assert llm.complete_calls == 1
    assert tools.searches == []
    assert tools.calls == []


def test_fast_path_streams_direct_answer_without_graph_loop():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    llm = DirectLlm()
    tools = MockTools()
    engine = AgentEngine(config=config, llm=llm, tools=tools, callbacks=HostCallbacks())

    events = list(engine.stream(RunRequest(query="2+2")))

    assert [event.get("type") for event in events] == ["debug", "delta", "done"]
    assert events[-1]["answer"] == "4"
    assert llm.stream_calls == 1
    assert llm.complete_calls == 0
    assert tools.searches == []
    assert tools.calls == []


def test_graph_smoke_approve_path():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    engine = AgentEngine(config=config, llm=MockLlm(), tools=MockTools(), callbacks=HostCallbacks())
    result = engine.run(RunRequest(query="Find SLA mentions"))
    assert "SLA" in result.answer
    assert result.review.get("verdict") == "APPROVE"
    assert result.artifacts


class BadArgsLlm(LlmProvider):
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return '{"action":"call_tool","name":"search_documents","arguments":{}}'

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def test_graph_stream_emits_answer_deltas_before_done():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    engine = AgentEngine(config=config, llm=MockLlm(), tools=MockTools(), callbacks=HostCallbacks())
    events = list(engine.stream(RunRequest(query="Find SLA mentions")))

    done_index = next(i for i, event in enumerate(events) if event.get("type") == "done")
    delta_events = [(i, event) for i, event in enumerate(events) if event.get("type") == "delta"]

    assert delta_events
    assert all(i < done_index for i, _event in delta_events)
    assert "".join(event.get("content", "") for _i, event in delta_events) == events[done_index]["answer"]


class SearchOnlyLlm(LlmProvider):
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return '{"action":"search_tools","query":"SLA documents"}'

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def _executor_state(**overrides):
    state = {
        "user_query": "Find SLA mentions",
        "phase": "executing",
        "iteration": {},
        "current_step_index": 0,
        "plan": {
            "goal": "Find SLA",
            "steps": [{"title": "Search", "action": "search", "tool_hint": "search_documents"}],
        },
        "candidate_tools": [],
        "tool_discovery_cache": {},
        "tool_calls": [],
        "artifacts": [],
        "events": [],
    }
    state.update(overrides)
    return state


def test_executor_reuses_tool_discovery_cache_without_second_search():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.nodes.executor import executor_node

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    tools = MockTools()

    first = executor_node(_executor_state(), config=config, llm=SearchOnlyLlm(), tools=tools)
    second = executor_node(
        _executor_state(tool_discovery_cache=first["tool_discovery_cache"]),
        config=config,
        llm=SearchOnlyLlm(),
        tools=tools,
    )

    assert tools.searches == ["SLA documents"]
    assert first["events"][-1]["cache_hit"] is False
    assert second["events"][-1]["cache_hit"] is True
    assert second["candidate_tools"] == first["candidate_tools"]


def test_executor_prunes_retained_artifacts_and_tool_calls():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.nodes.executor import _run_tool_and_record

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    config.policy.max_retained_artifacts = 2
    config.policy.max_retained_tool_calls = 2
    state = _executor_state(
        artifacts=[
            {"id": "old-low", "tool": "t", "summary": "old", "composite_score": 0.1, "step_index": 0},
            {"id": "old-high", "tool": "t", "summary": "old", "composite_score": 0.9, "step_index": 0},
        ],
        tool_calls=[
            {"name": "old1", "args_preview": "{}", "status": "ok", "latency_ms": 1, "error": None},
            {"name": "old2", "args_preview": "{}", "status": "ok", "latency_ms": 1, "error": None},
        ],
    )
    updates = {"events": []}

    _run_tool_and_record(
        state=state,
        config=config,
        tools=MockTools(),
        tool_name="search_documents",
        arguments={"query": "SLA"},
        updates=updates,
        iteration={},
        step_index=0,
        step_query="SLA",
        on_tool_call=None,
        on_artifact=None,
    )

    assert len(updates["artifacts"]) == 2
    assert "old-low" not in {artifact["id"] for artifact in updates["artifacts"]}
    assert len(updates["tool_calls"]) == 2
    assert [record["name"] for record in updates["tool_calls"]] == ["old2", "search_documents"]


def test_executor_validates_discovered_tool_schema_before_calling():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.nodes.executor import executor_node

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    tools = MockTools()
    state = {
        "user_query": "Find SLA mentions",
        "phase": "executing",
        "iteration": {},
        "current_step_index": 0,
        "plan": {
            "goal": "Find SLA",
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
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
        ],
        "tool_calls": [],
        "artifacts": [],
    }

    updates = executor_node(state, config=config, llm=BadArgsLlm(), tools=tools)

    assert tools.calls == []
    assert updates["tool_calls"][-1]["status"] == "invalid_args"
    assert "missing required argument: query" in updates["tool_calls"][-1]["error"]
