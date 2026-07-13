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
    assert updates["iteration"]["review_cycles"] == 0
    assert updates["plan"]["steps"][-1]["title"] == "Gather missing evidence"
    assert updates["plan"]["steps"][-1]["required_tools"] == ["get_panel_data"]
    assert updates["plan"]["steps"][-1]["require_row_level"] is True
    assert "get_panel_data" in updates["review_feedback"]
    assert updates["current_step_index"] == len(updates["plan"]["steps"]) - 1
    assert any(event.get("step") == "reviewer.re_explore" for event in updates["events"])


def test_re_explore_reuses_single_step_across_cycles():
    # Regression: each re-explore cycle used to append a fresh "Gather missing
    # evidence" step, growing the plan unboundedly. It must reuse one step.
    config = _config(max_explore_cycles=3)
    llm = _ReviewerLlm('{"verdict":"REVISE","issues":[],"missing_evidence":["call get_panel_data for the dashboard"],"required_changes":[]}')

    first = reviewer_node(_review_state(), config=config, llm=llm)
    steps_after_first = first["plan"]["steps"]
    assert steps_after_first[-1].get("origin") == "re_explore"

    # Feed the first cycle's plan/iteration back in (as the graph would) and
    # re-explore again — the plan length must not grow.
    second_state = _review_state(
        plan=first["plan"],
        iteration=dict(first["iteration"], review_cycles=1),
    )
    second = reviewer_node(second_state, config=config, llm=llm)
    assert len(second["plan"]["steps"]) == len(steps_after_first)
    assert second["plan"]["steps"][-1]["title"] == "Gather missing evidence"


def test_live_data_gate_ignores_bare_descriptive_words():
    from app.agent_workflow.evidence_grade import question_needs_live_data

    # Over-broad words alone must NOT trigger the quantitative-evidence gate.
    assert not question_needs_live_data("let use this dashboard to see if power is available")
    assert not question_needs_live_data("what is the current capacity story")
    # Genuine quantitative questions still do.
    assert question_needs_live_data("is there at least 30kv available in rtp")
    assert question_needs_live_data("how many panels are there")


def test_wording_only_revise_stays_text_revision():
    config = _config(max_explore_cycles=1)
    # No missing_evidence -> wording problem -> the bounded text-revision node.
    llm = _ReviewerLlm('{"verdict":"REVISE","issues":["tighten the phrasing"],"missing_evidence":[],"required_changes":["shorten it"]}')
    updates = reviewer_node(_review_state(), config=config, llm=llm)

    assert updates["phase"] == "revising"
    assert "explore_cycles" not in updates["iteration"] or updates["iteration"].get("explore_cycles", 0) == 0


def test_re_explore_resets_no_progress_counter():
    config = _config(max_explore_cycles=2)
    llm = _ReviewerLlm('{"verdict":"REVISE","missing_evidence":["call get_panel_data for the dashboard"],"required_changes":[]}')
    state = _review_state(iteration={"review_cycles": 0, "revision_cycles": 0, "no_progress_turns": 3})
    updates = reviewer_node(state, config=config, llm=llm)

    assert updates["phase"] == "executing"
    assert updates["iteration"]["no_progress_turns"] == 0


def test_re_explore_respects_cycle_cap():
    config = _config(max_explore_cycles=1)
    llm = _ReviewerLlm('{"verdict":"REVISE","missing_evidence":["still need get_panel_data"],"required_changes":[]}')
    # Budget already spent -> terminal incomplete evidence, not text revision.
    state = _review_state(iteration={"review_cycles": 0, "revision_cycles": 0, "explore_cycles": 1})
    updates = reviewer_node(state, config=config, llm=llm)

    assert updates["phase"] == "done"
    assert updates.get("error", "").startswith("Incomplete evidence:")
    assert any(event.get("step") == "reviewer.incomplete_evidence" for event in updates["events"])


def test_re_explore_disabled_when_cap_zero():
    config = _config(max_explore_cycles=0)
    llm = _ReviewerLlm('{"verdict":"REVISE","missing_evidence":["need get_panel_data"],"required_changes":[]}')
    updates = reviewer_node(_review_state(), config=config, llm=llm)

    assert updates["phase"] == "done"
    assert updates.get("error", "").startswith("Incomplete evidence:")


def test_sse_adapter_passes_through_re_explore_and_stop_fields():
    # The reviewer.re_explore / stop_condition activity fields must survive the
    # SSE whitelist, not be silently dropped.
    from app.api.sse_adapter import engine_event_to_sse

    name, data = engine_event_to_sse(
        {
            "type": "agent_activity",
            "label": "Reviewer requested more exploration",
            "explore_cycles": 2,
            "missing_evidence": ["need get_panel_data"],
            "stop_condition": "have panel data",
            "missing": ["get_cards"],
        }
    )
    assert name == "agent_activity"
    assert data["explore_cycles"] == 2
    assert data["stop_condition"] == "have panel data"
    assert data["missing"] == ["get_cards"]


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
    # No tool_calls and no candidate_tools -> nothing to re-explore with, so fail honestly.
    state = _review_state(tool_calls=[], candidate_tools=[])
    updates = reviewer_node(state, config=config, llm=llm)

    assert updates["phase"] == "done"
    assert updates.get("error", "").startswith("Incomplete evidence:")


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


class _FinishLlm:
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return '{"action":"finish_step"}'

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def test_executor_does_not_stop_while_plan_steps_remain():
    config = _config(max_no_progress_turns=1, min_progress_score=0.5)
    state = {
        "user_query": "q",
        "phase": "executing",
        "iteration": {"executor_turns": 1, "useful_artifacts_seen": 0, "no_progress_turns": 0},
        "current_step_index": 0,
        "plan": {
            "goal": "g",
            "steps": [
                {"title": "Discover", "action": "discover", "required_tools": ["list_dashboards"]},
                {"title": "Fetch", "action": "fetch", "tool_hint": "get_panel_data"},
            ],
        },
        "candidate_tools": [],
        "tool_discovery_cache": {},
        "tool_calls": [{"name": "list_dashboards", "status": "ok", "step_index": 0, "replan_id": 0}],
        "artifacts": [{"id": "a", "tool": "list_dashboards", "composite_score": 0.2, "step_index": 0}],
        "events": [],
    }
    updates = executor_node(state, config=config, llm=_FinishLlm(), tools=_PanelTools())

    assert updates["phase"] == "executing"
    assert not any(event.get("step") == "executor.no_progress_stop" for event in updates["events"])


def test_finish_step_honors_required_tool_called_run_wide_with_backticks():
    from app.agent_workflow.parsing import parse_plan_markdown

    plan = parse_plan_markdown(
        "### Goal\nFind power\n### Execution Plan\n"
        "1. **Search** — Action: search — Tool hint: auto — "
        "Expected output: dashboards — Stop condition: found — Required tools: `list_dashboards`"
    )
    config = _config()
    state = {
        "user_query": "q",
        "phase": "executing",
        "iteration": {"executor_turns": 2},
        "current_step_index": 0,
        "plan": plan,
        "candidate_tools": [],
        "tool_discovery_cache": {},
        "tool_calls": [{"name": "list_dashboards", "status": "ok", "step_index": 0, "replan_id": 0}],
        "artifacts": [{"id": "a", "tool": "list_dashboards", "composite_score": 0.8, "step_index": 0}],
        "events": [],
    }
    updates = executor_node(state, config=config, llm=_FinishLlm(), tools=_PanelTools())

    assert any(event.get("step") == "executor.finish_step" for event in updates["events"])
    assert updates.get("current_step_index") == 1


def test_approve_blocked_without_row_data_for_quantitative_question():
    config = _config(max_explore_cycles=1)
    llm = _ReviewerLlm('{"verdict":"APPROVE","issues":[],"missing_evidence":[],"required_changes":[]}')
    state = _review_state(
        user_query="Do we have at least 30 kW available in RTP?",
        draft_answer="Yes, capacity looks fine.",
        artifacts=[{"id": "a", "tool": "list_dashboards", "summary": "31 dashboards", "raw_ref": {"total": 31}}],
        tool_calls=[{"name": "list_dashboards", "status": "ok", "step_index": 0, "replan_id": 0}],
    )
    updates = reviewer_node(state, config=config, llm=llm)

    assert updates["phase"] == "executing"
    assert updates["review"]["verdict"] == "REVISE"
    assert any("row-level tool results" in item.lower() for item in updates["review"]["missing_evidence"])
    assert updates["plan"]["steps"][-1]["require_row_level"] is True


class _DraftLlm:
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return '{"action":"draft_answer","answer":"Yes, RTP has capacity."}'

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def test_draft_answer_blocked_without_row_data_for_quantitative_question():
    config = _config()
    state = {
        "user_query": "Do we have at least 30 kW available in RTP?",
        "phase": "executing",
        "iteration": {"executor_turns": 1, "no_progress_turns": 0},
        "current_step_index": 5,
        "plan": {
            "goal": "power",
            "steps": [
                {"title": "Gather missing evidence", "action": "gather", "origin": "re_explore", "require_row_level": True},
            ],
        },
        "candidate_tools": [_panel_tool()],
        "tool_discovery_cache": {},
        "tool_calls": [
            {"name": "get_dashboard_tokens", "status": "ok", "step_index": 0, "replan_id": 0},
        ],
        "artifacts": [
            {"id": "a", "tool": "get_dashboard_tokens", "raw_ref": {"facts": ["site=RTP"]}, "step_index": 0},
        ],
        "events": [],
    }
    updates = executor_node(state, config=config, llm=_DraftLlm(), tools=_PanelTools())

    assert "draft_answer" not in updates
    assert any(event.get("step") == "executor.row_level_evidence_missing" for event in updates["events"])


def test_executor_stops_when_exploration_stalls():
    # Generic no-progress early stop: a tool ran but produced no useful (above
    # threshold) new artifact, so the executor hands off instead of looping.
    config = _config(max_no_progress_turns=1, min_progress_score=0.5)
    state = {
        "user_query": "q",
        "phase": "executing",
        "iteration": {"executor_turns": 1, "useful_artifacts_seen": 0, "no_progress_turns": 0},
        "current_step_index": 0,
        "plan": {"goal": "g", "steps": [{"title": "s", "action": "a"}]},
        "candidate_tools": [],
        "tool_discovery_cache": {},
        "tool_calls": [{"name": "t", "status": "ok", "step_index": 0, "replan_id": 0}],
        "artifacts": [{"id": "a", "tool": "t", "composite_score": 0.2, "step_index": 0}],  # below 0.5 threshold
        "events": [],
    }
    updates = executor_node(state, config=config, llm=_FinishLlm(), tools=_PanelTools())

    assert updates["phase"] == "fact_extracting"
    assert any(event.get("step") == "executor.no_progress_stop" for event in updates["events"])


def test_executor_continues_when_useful_evidence_appears():
    # A new useful artifact resets the stall counter, so the run keeps going.
    config = _config(max_no_progress_turns=1, min_progress_score=0.2)
    state = {
        "user_query": "q",
        "phase": "executing",
        "iteration": {"executor_turns": 1, "useful_artifacts_seen": 0, "no_progress_turns": 0},
        "current_step_index": 0,
        "plan": {"goal": "g", "steps": [{"title": "s", "action": "a"}]},
        "candidate_tools": [],
        "tool_discovery_cache": {},
        "tool_calls": [{"name": "t", "status": "ok", "step_index": 0, "replan_id": 0}],
        "artifacts": [{"id": "a", "tool": "t", "composite_score": 0.8, "step_index": 0}],  # useful
        "events": [],
    }
    updates = executor_node(state, config=config, llm=_FinishLlm(), tools=_PanelTools())

    assert not any(event.get("step") == "executor.no_progress_stop" for event in updates["events"])


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
    _req, new_topic, _mem = eng._prepare_session(
        RunRequest(query="what is the error rate for the payment service", session_id="s1", history=history)
    )
    assert new_topic == []

    # A follow-up that refers back reuses them.
    _req2, follow, _mem2 = eng._prepare_session(
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


def test_streaming_maps_reviewer_re_explore_to_agent_activity():
    from app.agent_workflow.streaming import map_graph_update

    events = map_graph_update(
        {
            "events": [
                {
                    "step": "reviewer.re_explore",
                    "explore_cycles": 1,
                    "missing_evidence": ["list_dashboards"],
                }
            ]
        },
        {},
        node_name="reviewer",
    )
    activity = [event for event in events if event.get("type") == "agent_activity"]
    assert activity
    assert activity[0]["phase"] == "running"
    assert activity[0]["missing_evidence"] == ["list_dashboards"]
