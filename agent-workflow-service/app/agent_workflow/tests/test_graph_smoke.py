from __future__ import annotations

from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider
from app.agent_workflow.streaming import HostCallbacks, RunRequest


class MockTools(ToolProvider):
    def __init__(self):
        self.searches: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    def search_tools(self, query: str, *, limit: int = 25, allowlist: list[str] | None = None) -> list[ToolCandidate]:
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


_PLAN_MD = (
    "### Goal\nFind SLA\n### Assumptions\nNone\n### Risks and edge cases\nNone\n"
    "### Execution plan\n1. **Search** — Action: search — Tool hint: search_documents\n"
    "### Acceptance criteria\n- SLA found\n### Suggested user-facing structure\nSummary"
)


class RoleAwareLlm(LlmProvider):
    """A mock LLM that plays each node by its prompt, not by call order.

    Call-count mocks drift whenever the node sequence changes and can feed one
    node's output to another (e.g. an executor action to the reviewer). Keying
    on the node's own system prompt keeps golden-path tests stable.
    """

    def __init__(self, *, reviewer_output: str | None = None):
        # By default the reviewer approves cleanly with JSON.
        self.reviewer_output = reviewer_output or '{"verdict":"APPROVE","issues":[],"missing_evidence":[],"required_changes":[]}'
        self.executor_step = 0
        self.roles: list[str] = []

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""
        if "planner markdown sections" in user or system.startswith("# Planner"):
            self.roles.append("planner")
            return _PLAN_MD
        if "synthesizer node" in system:
            self.roles.append("synthesizer")
            return "Found SLA in doc-1 page 2."
        if "compress an agent's working memory" in system:
            self.roles.append("summarizer")
            return "Confirmed facts:\n- found SLA in doc-1 page 2"
        if "reviewer node" in system:
            self.roles.append("reviewer")
            return self.reviewer_output
        if "revision node" in system:
            self.roles.append("revision")
            return "Found SLA in doc-1 page 2 (revised)."
        if "final answer renderer" in system:
            self.roles.append("finalizer")
            return "Found SLA in doc-1 page 2."
        # Otherwise this is the executor choosing the next action.
        self.roles.append("executor")
        actions = [
            '{"action":"search_tools","query":"SLA documents"}',
            '{"action":"call_tool","name":"search_documents","arguments":{"query":"SLA documents"}}',
            '{"action":"finish_step"}',
        ]
        action = actions[min(self.executor_step, len(actions) - 1)]
        self.executor_step += 1
        return action

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def test_golden_path_runs_all_nodes_and_approves():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    llm = RoleAwareLlm()
    engine = AgentEngine(config=config, llm=llm, tools=MockTools(), callbacks=HostCallbacks())

    result = engine.run(RunRequest(query="Find SLA mentions"))

    # planner -> executor -> fact_extractor -> synthesizer -> reviewer -> finalizer
    assert result.review.get("verdict") == "APPROVE"
    assert "SLA" in result.answer
    assert result.error is None
    assert result.artifacts, "the executor should have produced a tool-backed artifact"
    assert "planner" in llm.roles
    assert "synthesizer" in llm.roles
    assert "reviewer" in llm.roles
    steps = [event.get("step") for event in result.events]
    assert "fact_extractor.completed" in steps
    assert "synthesizer.completed" in steps
    assert "reviewer.completed" in steps


def test_run_emits_exactly_one_done_event():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    seen: list[dict] = []
    callbacks = HostCallbacks(on_event=seen.append)
    engine = AgentEngine(config=config, llm=RoleAwareLlm(), tools=MockTools(), callbacks=callbacks)

    engine.run(RunRequest(query="Find SLA mentions"))

    # The reviewer sets phase=done as a routing signal, but only the finalizer
    # should emit the terminal done event — no duplicates.
    done_events = [event for event in seen if event.get("type") == "done"]
    assert len(done_events) == 1


def test_revise_path_runs_revision_before_finalizing():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    llm = RoleAwareLlm(reviewer_output='{"verdict":"REVISE","issues":["tighten wording"],"required_changes":["cite the doc"]}')
    engine = AgentEngine(config=config, llm=llm, tools=MockTools(), callbacks=HostCallbacks())

    result = engine.run(RunRequest(query="Find SLA mentions"))

    # reviewer -> revision -> finalizer
    assert "revised" in result.answer
    assert "revision" in llm.roles
    steps = [event.get("step") for event in result.events]
    assert "reviewer.completed" in steps
    assert "revision.completed" in steps


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
    engine = AgentEngine(config=config, llm=RoleAwareLlm(), tools=MockTools(), callbacks=HostCallbacks())
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


class FinishStepLlm(LlmProvider):
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return '{"action":"finish_step"}'

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


class RejectReviewerLlm(LlmProvider):
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return (
            "### Verdict\nREJECT\n"
            "### Issues found\n- Missing grounded list\n"
            "### Missing evidence\n- Did not cite artifacts\n"
            "### Required changes\n1. Use existing artifacts\n"
            "### Approved answer\n"
        )

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


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


def test_executor_breaks_repeated_search_loop_with_existing_candidates():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.nodes.executor import executor_node

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    tools = MockTools()
    candidates = [
        {
            "name": "get_dashboard",
            "title": "Get Dashboard",
            "description": "Return panel metadata for one dashboard",
            "score": 0.9,
            "input_schema": {"type": "object", "properties": {}},
        }
    ]

    first = executor_node(
        _executor_state(candidate_tools=candidates, iteration={}),
        config=config,
        llm=SearchOnlyLlm(),
        tools=tools,
    )
    assert first["events"][-1]["step"] == "executor.tool_candidates_available"
    assert tools.calls == []

    second = executor_node(
        _executor_state(
            candidate_tools=candidates,
            iteration=first["iteration"],
            artifacts=first.get("artifacts") or [],
            tool_calls=first.get("tool_calls") or [],
        ),
        config=config,
        llm=SearchOnlyLlm(),
        tools=tools,
    )
    assert tools.calls == [("get_dashboard", {})]
    assert any(event.get("step") == "executor.search_loop_breaker" for event in second["events"])

    third = executor_node(
        _executor_state(
            candidate_tools=candidates,
            iteration=second["iteration"],
            artifacts=second.get("artifacts") or [],
            tool_calls=second.get("tool_calls") or [],
        ),
        config=config,
        llm=SearchOnlyLlm(),
        tools=tools,
    )
    assert third.get("current_step_index") == 1
    assert any(event.get("step") == "executor.finish_step" for event in third["events"])


def test_executor_finish_last_step_hands_off_to_fact_extractor():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.nodes.executor import executor_node

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    state = _executor_state(
        artifacts=[
            {
                "id": "a1",
                "tool": "list_dashboards",
                "summary": "- name=dbx_overview, app=zabbix_poc, panel_count=12",
                "raw_ref": {"type": "list", "total": 1, "truncated": False},
                "composite_score": 0.8,
                "step_index": 0,
            }
        ]
    )

    updates = executor_node(state, config=config, llm=FinishStepLlm(), tools=MockTools())

    assert updates["phase"] == "fact_extracting"
    assert any(event.get("step") == "executor.completed_steps" for event in updates["events"])
    assert "draft_answer" not in updates


def test_reviewer_revise_keeps_artifacts_and_tool_calls():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.nodes.reviewer import reviewer_node

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    state = {
        "phase": "reviewing",
        "iteration": {"review_cycles": 0, "revision_cycles": 0},
        "draft_answer": "ungrounded answer",
        "artifacts": [{"id": "a1", "tool": "list_dashboards", "summary": "dashboards"}],
        "tool_calls": [{"name": "list_dashboards", "status": "ok"}],
        "candidate_tools": [{"name": "list_dashboards"}],
    }

    class ReviseReviewerLlm:
        def complete(self, messages, *, max_tokens: int = 1024) -> str:
            return '{"verdict":"REVISE","issues":["unsupported"],"required_changes":["Use the facts only"]}'

        def stream(self, messages, *, max_tokens: int = 1024):
            yield self.complete(messages, max_tokens=max_tokens)

    updates = reviewer_node(state, config=config, llm=ReviseReviewerLlm())

    assert updates["phase"] == "revising"
    assert "artifacts" not in updates
    assert "tool_calls" not in updates
    assert "candidate_tools" not in updates


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


class SlowLlm(LlmProvider):
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        import time

        time.sleep(0.05)
        return "too late"

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


class SlowTools(MockTools):
    def call_tool(self, name: str, arguments: dict) -> dict:
        import time

        time.sleep(0.05)
        return super().call_tool(name, arguments)


def test_planner_deadline_returns_timeout_result():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    config.policy.llm_timeout_seconds = 0.01
    engine = AgentEngine(config=config, llm=SlowLlm(), tools=MockTools(), callbacks=HostCallbacks())

    result = engine.run(RunRequest(query="Find SLA mentions"))

    assert result.error and "planner LLM call exceeded" in result.error
    assert "timed out" in result.answer.lower()


def test_tool_deadline_records_error_artifact():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.nodes.executor import _run_tool_and_record

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    config.policy.tool_timeout_seconds = 0.01
    updates = {"events": []}

    _run_tool_and_record(
        state=_executor_state(),
        config=config,
        tools=SlowTools(),
        tool_name="search_documents",
        arguments={"query": "SLA"},
        updates=updates,
        iteration={},
        step_index=0,
        step_query="SLA",
        on_tool_call=None,
        on_artifact=None,
    )

    assert updates["tool_calls"][-1]["status"] == "error"
    assert "tool call search_documents exceeded" in updates["tool_calls"][-1]["error"]


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


def test_reviewer_blocks_approve_when_trello_cards_missing():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.nodes.reviewer import reviewer_node

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")

    class ApproveReviewerLlm(LlmProvider):
        def complete(self, messages, *, max_tokens: int = 1024) -> str:
            return (
                "### Verdict\nAPPROVE\n### Issues found\nNone\n### Missing evidence\nNone\n"
                "### Required changes\nNone\n### Approved answer\nThere are 0 cards on the board."
            )

        def stream(self, messages, *, max_tokens: int = 1024):
            yield self.complete(messages, max_tokens=max_tokens)

    state = {
        "user_query": "How many cards are on my Trello board?",
        "phase": "reviewing",
        "iteration": {"review_cycles": 0},
        "draft_answer": "There are 0 cards on the board.",
        "artifacts": [],
        "tool_calls": [{"name": "list_boards", "status": "ok"}],
    }

    updates = reviewer_node(state, config=config, llm=ApproveReviewerLlm())

    assert updates["review"]["verdict"] == "REVISE"
    assert updates["phase"] == "revising"
    assert any("get_cards" in item for item in updates["review"].get("required_changes") or [])


class DuplicateToolLlm(LlmProvider):
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return '{"action":"call_tool","name":"list_boards","arguments":{}}'

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def test_executor_allows_retry_after_replan_despite_prior_step_zero_artifacts():
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.nodes.executor import executor_node

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    tools = MockTools()
    candidates = [
        {
            "name": "list_boards",
            "title": "List Boards",
            "description": "List Trello boards",
            "score": 0.9,
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    state = _executor_state(
        iteration={"replans": 1},
        candidate_tools=candidates,
        artifacts=[
            {
                "id": "old-boards",
                "tool": "list_boards",
                "summary": "old boards",
                "step_index": 0,
                "replan_id": 0,
                "composite_score": 0.5,
            }
        ],
    )

    updates = executor_node(state, config=config, llm=DuplicateToolLlm(), tools=tools)

    assert tools.calls == [("list_boards", {})]
    assert not any(event.get("step") == "executor.duplicate_tool_skipped" for event in updates["events"])
