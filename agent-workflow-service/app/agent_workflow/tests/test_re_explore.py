from __future__ import annotations

import json
from pathlib import Path

from app.agent_workflow.config import load_agent_config, parse_agent_config
from app.agent_workflow.nodes.executor import executor_node
from app.agent_workflow.nodes.reviewer import reviewer_node


def _config(**policy):
    base = {
        "name": "re",
        "prompts_inline": {"planner": "p", "executor": "e", "reviewer": "r"},
        "llm": {"base_url": "http://llm.local/v1", "model": "m"},
        "policy": {"enable_fast_path": False, **policy},
    }
    return parse_agent_config(base)


class _ReviewerLlm:
    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return self.payload

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.payload


def _review_state(**overrides):
    state = {
        "user_query": "How many panels does the dashboard have?",
        "phase": "reviewing",
        "iteration": {"review_cycles": 0, "revision_cycles": 0},
        "draft_answer": "It has some panels.",
        "artifacts": [],
        "tool_calls": [{"name": "get_dashboard", "status": "ok", "step_index": 0, "replan_id": 0}],
        "candidate_tools": [],
        "plan": {"goal": "count panels", "steps": [{"title": "Look up", "action": "look"}]},
    }
    state.update(overrides)
    return state


# --- Reviewer routing: evidence-revise vs text-revise -----------------------


def test_missing_evidence_routes_to_executor_not_revision():
    config = _config(max_explore_cycles=1)
    llm = _ReviewerLlm('{"verdict":"REVISE","issues":[],"missing_evidence":["call get_panel_data for the dashboard"],"required_changes":[]}')
    updates = reviewer_node(_review_state(), config=config, llm=llm)

    assert updates["phase"] == "executing"  # re-enter executor
    assert updates["iteration"]["explore_cycles"] == 1
    assert updates["plan"]["steps"][-1]["title"] == "Gather missing evidence"
    assert "get_panel_data" in updates["review_feedback"]
    assert updates["current_step_index"] == len(updates["plan"]["steps"]) - 1
    assert any(event.get("step") == "reviewer.re_explore" for event in updates["events"])


def test_wording_only_revise_stays_text_revision():
    config = _config(max_explore_cycles=1)
    # No missing_evidence -> wording problem -> the bounded text-revision node.
    llm = _ReviewerLlm('{"verdict":"REVISE","issues":["tighten the phrasing"],"missing_evidence":[],"required_changes":["shorten it"]}')
    updates = reviewer_node(_review_state(), config=config, llm=llm)

    assert updates["phase"] == "revising"
    assert "explore_cycles" not in updates["iteration"] or updates["iteration"].get("explore_cycles", 0) == 0


def test_re_explore_respects_cycle_cap():
    config = _config(max_explore_cycles=1)
    llm = _ReviewerLlm('{"verdict":"REVISE","missing_evidence":["still need get_panel_data"],"required_changes":[]}')
    # Budget already spent -> falls back to text revision instead of looping.
    state = _review_state(iteration={"review_cycles": 0, "revision_cycles": 0, "explore_cycles": 1})
    updates = reviewer_node(state, config=config, llm=llm)

    assert updates["phase"] == "revising"


def test_re_explore_disabled_when_cap_zero():
    config = _config(max_explore_cycles=0)
    llm = _ReviewerLlm('{"verdict":"REVISE","missing_evidence":["need get_panel_data"],"required_changes":[]}')
    updates = reviewer_node(_review_state(), config=config, llm=llm)

    assert updates["phase"] == "revising"  # re-exploration turned off


def test_formatting_gap_routes_to_text_revision_not_re_explore():
    # An APPROVE whose only problem is missing markdown structure must become a
    # text-revise (wording), never an evidence-revise that re-runs tools.
    config = _config(max_explore_cycles=2)
    llm = _ReviewerLlm('{"verdict":"APPROVE","issues":[],"missing_evidence":[],"required_changes":[]}')
    plain = "This is a long plain answer with no markdown structure at all. " * 6
    state = _review_state(
        user_query="give me a summary",
        draft_answer=plain,
        tool_calls=[{"name": "search", "status": "ok", "step_index": 0, "replan_id": 0}],
    )
    updates = reviewer_node(state, config=config, llm=llm)

    assert updates["phase"] == "revising"  # text-revise, not "executing"
    assert updates["iteration"].get("explore_cycles", 0) == 0
    assert any("markdown" in item.lower() for item in updates["review"].get("required_changes") or [])
    assert not updates["review"].get("missing_evidence")


def test_re_explore_skipped_when_no_tools_available():
    config = _config(max_explore_cycles=1)
    llm = _ReviewerLlm('{"verdict":"REVISE","missing_evidence":["need more data"],"required_changes":[]}')
    # No tool_calls and no candidate_tools -> nothing to re-explore with.
    state = _review_state(tool_calls=[], candidate_tools=[])
    updates = reviewer_node(state, config=config, llm=llm)

    assert updates["phase"] == "revising"


# --- Executor guard: same tool, different arguments -------------------------


def _panel_tool():
    return {
        "name": "get_panel_data",
        "title": "Get Panel Data",
        "description": "Return data for a panel",
        "score": 0.9,
        "input_schema": {
            "type": "object",
            "properties": {"panel": {"type": "string"}},
            "required": ["panel"],
            "additionalProperties": False,
        },
    }


class _CallPanelLlm:
    def __init__(self, panel: str):
        self.panel = panel

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return json.dumps({"action": "call_tool", "name": "get_panel_data", "arguments": {"panel": self.panel}})

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


class _PanelTools:
    def __init__(self):
        self.calls = []

    def search_tools(self, query, *, limit=25, allowlist=None):
        return []

    def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return {"ok": True, "panel": arguments.get("panel"), "rows": [{"v": 1}]}


def _exec_state(prior_args_preview: str):
    return {
        "user_query": "panel data",
        "phase": "executing",
        "iteration": {},
        "current_step_index": 0,
        "plan": {"goal": "g", "steps": [{"title": "Panels", "action": "get panel data"}]},
        "candidate_tools": [_panel_tool()],
        "tool_discovery_cache": {},
        "tool_calls": [
            {"name": "get_panel_data", "status": "ok", "step_index": 0, "replan_id": 0, "args_preview": prior_args_preview}
        ],
        "artifacts": [],
        "events": [],
    }


def test_same_tool_different_args_is_allowed():
    config = _config()
    tools = _PanelTools()
    prior = json.dumps({"panel": "cpu"})[:300]
    # Model asks for a *different* panel than the one already recorded.
    updates = executor_node(_exec_state(prior), config=config, llm=_CallPanelLlm("memory"), tools=tools)

    assert tools.calls == [("get_panel_data", {"panel": "memory"})]
    assert not any(e.get("step") == "executor.duplicate_tool_skipped" for e in updates["events"])


def test_same_tool_same_args_is_skipped():
    config = _config()
    tools = _PanelTools()
    prior = json.dumps({"panel": "cpu"})[:300]
    # Model repeats the identical call -> skipped, no second execution.
    updates = executor_node(_exec_state(prior), config=config, llm=_CallPanelLlm("cpu"), tools=tools)

    assert tools.calls == []
    assert any(e.get("step") == "executor.duplicate_tool_skipped" for e in updates["events"])


# --- Step 5: cross-turn artifacts reused only on follow-ups -----------------


class _NoopLlm:
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return "{}"

    def stream(self, messages, *, max_tokens: int = 1024):
        yield "{}"


class _NoopTools:
    def search_tools(self, query, *, limit=25, allowlist=None):
        return []

    def call_tool(self, name, arguments):
        return {"ok": True}


def test_persisted_artifacts_reused_only_on_followups(monkeypatch):
    from app.agent_workflow import engine as engine_mod
    from app.agent_workflow.engine import AgentEngine
    from app.agent_workflow.streaming import HostCallbacks, RunRequest

    config = _config(cross_turn_artifact_persistence=True)
    eng = AgentEngine(config=config, llm=_NoopLlm(), tools=_NoopTools(), callbacks=HostCallbacks())

    class _Store:
        def load(self, session_id):
            return [{"id": "old", "tool": "run_search", "summary": "stale", "composite_score": 0.5}]

    monkeypatch.setattr(engine_mod, "is_cross_turn_persistence_active", lambda enabled: True)
    monkeypatch.setattr(engine_mod, "get_artifact_store", lambda: _Store())

    history = [{"role": "user", "content": "list dashboards"}, {"role": "assistant", "content": "12 dashboards"}]

    # A genuinely new topic must not inherit the prior turn's artifacts.
    _req, new_topic = eng._prepare_session(
        RunRequest(query="what is the error rate for the payment service", session_id="s1", history=history)
    )
    assert new_topic == []

    # A follow-up that refers back reuses them.
    _req2, follow = eng._prepare_session(
        RunRequest(query="how many of those are there?", session_id="s1", history=history)
    )
    assert follow and follow[0]["id"] == "old"


# --- End-to-end: reviewer re-enters the executor and the run completes -------


class _ExploreRunLlm:
    """Role-aware LLM: the reviewer asks for more evidence once, then approves."""

    def __init__(self):
        self.executor_step = 0
        self.review_calls = 0
        self.roles: list[str] = []

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""
        if "planner markdown sections" in user or system.startswith("# Planner"):
            self.roles.append("planner")
            return (
                "### Search Query\nfind SLA\n### Goal\nFind SLA\n"
                "### Execution Plan\n1. **Search** — Action: search — Tool hint: search_documents\n"
                "### Acceptance Criteria\n- found"
            )
        if "synthesizer node" in system:
            self.roles.append("synthesizer")
            return "Found SLA in doc-1."
        if "reviewer node" in system:
            self.roles.append("reviewer")
            self.review_calls += 1
            if self.review_calls == 1:
                return '{"verdict":"REVISE","missing_evidence":["gather more detail with search_documents"],"required_changes":[]}'
            return '{"verdict":"APPROVE","issues":[],"missing_evidence":[],"required_changes":[]}'
        if "final answer renderer" in system:
            self.roles.append("finalizer")
            return "Found SLA in doc-1."
        self.roles.append("executor")
        actions = [
            '{"action":"search_tools","query":"SLA"}',
            '{"action":"call_tool","name":"search_documents","arguments":{"query":"SLA"}}',
            '{"action":"finish_step"}',
        ]
        action = actions[min(self.executor_step, len(actions) - 1)]
        self.executor_step += 1
        return action

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def test_reviewer_re_enters_executor_end_to_end():
    from app.agent_workflow.engine import AgentEngine
    from app.agent_workflow.streaming import HostCallbacks, RunRequest
    from app.agent_workflow.tests.test_graph_smoke import MockTools

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    llm = _ExploreRunLlm()
    engine = AgentEngine(config=config, llm=llm, tools=MockTools(), callbacks=HostCallbacks())

    result = engine.run(RunRequest(query="Find SLA mentions"))

    # The reviewer ran twice (revise then approve), with an executor visit in between.
    first_reviewer = llm.roles.index("reviewer")
    assert "executor" in llm.roles[first_reviewer + 1:], "reviewer should have re-entered the executor"
    assert llm.roles.count("reviewer") >= 2
    assert result.answer
    assert result.error is None
    assert any(e.get("step") == "reviewer.re_explore" for e in result.events)
