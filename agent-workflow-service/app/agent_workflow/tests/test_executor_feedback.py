from __future__ import annotations

"""Regression tests for the executor feedback loop and loop-escape arbitration.

These lock in the fixes for the stalled runs captured in analysis.md: unparsed
multi-action JSON becoming a draft, guards vetoing actions without telling the
model why, the search loop breaker forcing schema-invalid calls, and REJECT
verdicts shipping garbage instead of re-exploring.
"""

from pathlib import Path

from app.agent_workflow.config import parse_agent_config
from app.agent_workflow.context.builder import ContextBuilder
from app.agent_workflow.nodes.executor import executor_node
from app.agent_workflow.nodes.reviewer import reviewer_node
from app.agent_workflow.parsing import parse_executor_action
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider


def _config(**policy):
    return parse_agent_config(
        {
            "name": "feedback",
            "prompts_inline": {"planner": "p", "executor": "e", "reviewer": "r"},
            "llm": {"base_url": "http://llm.local/v1", "model": "m"},
            "policy": {"enable_fast_path": False, **policy},
        }
    )


class _ScriptedLlm(LlmProvider):
    def __init__(self, payload: str):
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        self.prompts.append("\n".join(m["content"] for m in messages))
        return self.payload

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


class _NoopTools(ToolProvider):
    def search_tools(self, query: str, *, limit: int = 25, allowlist=None) -> list[ToolCandidate]:
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        return {"ok": True}


_PANEL_TOOL = {
    "name": "get_panel_data",
    "title": "Get Panel Data",
    "description": "Fetch live rows for a panel",
    "score": 0.9,
    "input_schema": {
        "type": "object",
        "properties": {"panel_id": {"type": "integer"}},
        "required": ["panel_id"],
    },
}


def _state(**overrides):
    state = {
        "user_query": "check available power",
        "phase": "executing",
        "iteration": {},
        "current_step_index": 0,
        "plan": {"goal": "check", "steps": [{"title": "Fetch", "action": "fetch data"}]},
        "candidate_tools": [],
        "tool_discovery_cache": {},
        "tool_calls": [],
        "artifacts": [],
        "events": [],
    }
    state.update(overrides)
    return state


# --- parsing: multiple JSON actions in one response --------------------------


def test_parse_executor_action_takes_first_of_multiple_objects():
    raw = '{"action":"search_panels","query":"autopod"} {"action":"list_dashboards"}'
    action = parse_executor_action(raw)
    assert action == {"action": "search_panels", "query": "autopod"}


def test_parse_executor_action_prefers_action_object_in_prose():
    raw = 'Calling now: {"action":"call_tool","name":"get_dashboard","arguments":{"name":"x"}} ok?'
    action = parse_executor_action(raw)
    assert action["action"] == "call_tool"
    assert action["arguments"] == {"name": "x"}


# --- guidance feedback loop ---------------------------------------------------


def test_invalid_args_produce_guidance_and_reach_next_prompt():
    config = _config()
    llm = _ScriptedLlm('{"action":"call_tool","name":"get_panel_data","arguments":{}}')
    updates = executor_node(
        _state(candidate_tools=[_PANEL_TOOL]),
        config=config,
        llm=llm,
        tools=_NoopTools(),
    )
    guidance = updates.get("executor_guidance") or []
    assert guidance and "panel_id" in guidance[0]

    # The next turn's executor prompt must carry the correction.
    prompt = "\n".join(
        m["content"]
        for m in ContextBuilder(config).build(_state(executor_guidance=guidance), "executor")
    )
    assert "Corrections from your last action" in prompt
    assert "panel_id" in prompt


def test_clean_turn_clears_stale_guidance():
    config = _config()
    llm = _ScriptedLlm('{"action":"call_tool","name":"get_panel_data","arguments":{}}')
    updates = executor_node(
        _state(candidate_tools=[_PANEL_TOOL], executor_guidance=["old correction"]),
        config=config,
        llm=llm,
        tools=_NoopTools(),
    )
    # Guidance is rebuilt each turn: the stale entry is gone, only this turn's remains.
    assert "old correction" not in (updates.get("executor_guidance") or [])


def test_recent_tool_calls_show_errors_in_prompt():
    config = _config()
    state = _state(
        tool_calls=[
            {
                "name": "get_dashboard",
                "status": "invalid_args",
                "args_preview": "{}",
                "error": "missing required argument: name",
            }
        ]
    )
    prompt = "\n".join(m["content"] for m in ContextBuilder(config).build(state, "executor"))
    assert "missing required argument: name" in prompt


# --- loop breaker must not force schema-invalid calls -------------------------


def test_search_loop_breaker_skips_tools_with_required_args():
    config = _config()
    llm = _ScriptedLlm('{"action":"search_tools","query":"power"}')
    first = executor_node(_state(candidate_tools=[_PANEL_TOOL]), config=config, llm=llm, tools=_NoopTools())
    second = executor_node(
        _state(candidate_tools=[_PANEL_TOOL], iteration=first["iteration"]),
        config=config,
        llm=llm,
        tools=_NoopTools(),
    )
    # No forced get_panel_data({}) — instead the model is told which args to fill.
    assert not any(e.get("step") == "executor.tool_args_invalid" for e in second["events"])
    guidance = second.get("executor_guidance") or []
    assert guidance and "panel_id" in guidance[-1]


# --- draft veto deadlock break -------------------------------------------------


def test_draft_veto_yields_after_no_progress_cap():
    # Mirrors the analysis.md run: mid-plan (later steps pending, so the
    # no-progress early stop stays suppressed) with the follow-up guard vetoing
    # draft_answer every turn. After the stall cap the draft must be accepted.
    config = _config(max_no_progress_turns=3)
    llm = _ScriptedLlm('{"action":"draft_answer","answer":"Best effort from metadata."}')
    follow_up_runtime = {"follow_up": True, "require_tools": True}
    two_step_plan = {
        "goal": "check",
        "steps": [{"title": "Fetch", "action": "fetch"}, {"title": "Analyze", "action": "analyze"}],
    }

    blocked = executor_node(
        _state(
            plan=two_step_plan,
            runtime_context=follow_up_runtime,
            tool_calls=[{"name": "x", "status": "error", "step_index": 0, "replan_id": 0}],
        ),
        config=config,
        llm=llm,
        tools=_NoopTools(),
    )
    assert any(e.get("step") == "executor.follow_up_evidence_missing" for e in blocked["events"])
    assert "draft_answer" not in blocked
    assert blocked.get("executor_guidance")  # the model is told why it was blocked

    deadlocked = executor_node(
        _state(
            plan=two_step_plan,
            runtime_context=follow_up_runtime,
            tool_calls=[{"name": "x", "status": "error", "step_index": 0, "replan_id": 0}],
            iteration={"no_progress_turns": 3, "useful_artifacts_seen": 0},
        ),
        config=config,
        llm=llm,
        tools=_NoopTools(),
    )
    assert deadlocked.get("draft_answer") == "Best effort from metadata."
    assert any(e.get("step") == "executor.finish_deadlock_break" for e in deadlocked["events"])


# --- REJECT re-explores when evidence is missing -------------------------------


def test_reject_with_missing_evidence_re_explores():
    config = _config(max_explore_cycles=1)
    llm = _ScriptedLlm('{"verdict":"REJECT","issues":["no data"],"missing_evidence":["call get_panel_data for live rows"],"required_changes":[]}')
    state = {
        "user_query": "check available power",
        "phase": "reviewing",
        "iteration": {"review_cycles": 0, "revision_cycles": 0},
        "draft_answer": "Cannot determine.",
        "artifacts": [],
        "tool_calls": [{"name": "list_dashboards", "status": "ok", "step_index": 0, "replan_id": 0}],
        "candidate_tools": [],
        "plan": {"goal": "check", "steps": [{"title": "Fetch", "action": "fetch"}]},
    }
    updates = reviewer_node(state, config=config, llm=llm)
    assert updates["phase"] == "executing"  # re-explore instead of shipping the rejected draft
    assert any(e.get("step") == "reviewer.re_explore" for e in updates["events"])
