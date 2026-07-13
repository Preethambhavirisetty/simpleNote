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


# --- tool-name-as-action recovery (analysis-2 regression) ---------------------


class _RecordingTools(ToolProvider):
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def search_tools(self, query: str, *, limit: int = 25, allowlist=None) -> list[ToolCandidate]:
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"ok": True, "items": [{"panel": "ROWS AVAILABILITY"}]}


_SEARCH_PANELS_TOOL = {
    "name": "search_panels",
    "title": "Search Panels",
    "description": "Semantic search over dashboard panels",
    "score": 0.9,
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}


def test_tool_name_as_action_recovers_into_call_tool():
    # analysis-2: {"action":"search_panels","query":...} fell through to the
    # draft path and the whole run made zero tool calls. It must become a call.
    config = _config()
    tools = _RecordingTools()
    llm = _ScriptedLlm('{"action":"search_panels","query":"autopod rows availability"}')
    updates = executor_node(
        _state(candidate_tools=[_SEARCH_PANELS_TOOL]),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert tools.calls == [("search_panels", {"query": "autopod rows availability"})]
    assert any(e.get("step") == "executor.action_recovered" for e in updates["events"])
    assert "draft_answer" not in updates


def test_unknown_action_gets_guidance_not_silent_draft():
    config = _config()
    llm = _ScriptedLlm('{"action":"fetch_rows","target":"lab"}')
    updates = executor_node(
        _state(candidate_tools=[_SEARCH_PANELS_TOOL]),
        config=config,
        llm=llm,
        tools=_RecordingTools(),
    )
    assert "draft_answer" not in updates  # not silently drafted
    guidance = updates.get("executor_guidance") or []
    assert guidance and "call_tool" in guidance[0]
    assert any(e.get("step") == "executor.unknown_action" for e in updates["events"])


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


def test_draft_veto_becomes_incomplete_after_no_progress_cap():
    # Mid-plan with the follow-up guard vetoing draft_answer every turn. After
    # the stall cap the loop must stop honestly, not accept a metadata draft.
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
    assert deadlocked.get("phase") == "done"
    assert deadlocked.get("error", "").startswith("Incomplete evidence:")
    assert "Best effort from metadata" not in deadlocked.get("final_answer", "")
    assert any(e.get("step") == "executor.incomplete_evidence" for e in deadlocked["events"])


# --- deterministic argument repair (a.txt: 4 wasted turns on missing `name`) ---


_TOKENS_TOOL = {
    "name": "get_dashboard_tokens",
    "title": "Get Dashboard Tokens",
    "description": "Return the token catalog for a dashboard",
    "score": 0.9,
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}


def test_missing_required_arg_repaired_from_prior_call():
    config = _config()
    tools = _RecordingTools()
    # Model asks for get_dashboard_tokens with NO args; a prior successful call
    # already used name=autopod_rows_availability — repair must fill it and run.
    llm = _ScriptedLlm('{"action":"call_tool","name":"get_dashboard_tokens","arguments":{}}')
    updates = executor_node(
        _state(
            candidate_tools=[_TOKENS_TOOL],
            tool_calls=[
                {
                    "name": "get_dashboard",
                    "status": "ok",
                    "step_index": 0,
                    "replan_id": 0,
                    "args_preview": '{"name": "autopod_rows_availability"}',
                }
            ],
        ),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert tools.calls == [("get_dashboard_tokens", {"name": "autopod_rows_availability"})]
    assert any(e.get("step") == "executor.arguments_repaired" for e in updates["events"])
    assert not any(e.get("step") == "executor.tool_args_invalid" for e in updates["events"])


def test_missing_required_arg_repaired_from_memory_slot():
    config = _config()
    tools = _RecordingTools()
    llm = _ScriptedLlm('{"action":"call_tool","name":"get_dashboard_tokens","arguments":{}}')
    updates = executor_node(
        _state(
            candidate_tools=[_TOKENS_TOOL],
            conversation_memory={"name": {"value": "aiera_power", "turn": 1}},
        ),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert tools.calls == [("get_dashboard_tokens", {"name": "aiera_power"})]


def test_unrepairable_missing_arg_still_produces_guidance():
    config = _config()
    tools = _RecordingTools()
    llm = _ScriptedLlm('{"action":"call_tool","name":"get_dashboard_tokens","arguments":{}}')
    updates = executor_node(
        _state(candidate_tools=[_TOKENS_TOOL]),  # nothing known to fill from
        config=config,
        llm=llm,
        tools=tools,
    )
    assert tools.calls == []
    assert any(e.get("step") == "executor.tool_args_invalid" for e in updates["events"])
    assert any("name" in g for g in (updates.get("executor_guidance") or []))


_PANEL_DATA_TOOL = {
    "name": "get_panel_data",
    "title": "Get Panel Data",
    "description": "Fetch live rows for a panel",
    "score": 0.9,
    "input_schema": {
        "type": "object",
        "properties": {"panel_id": {"type": "integer"}, "panel_tokens": {"type": "object"}},
        "required": ["panel_id"],
    },
}


def test_missing_arg_repaired_from_tool_result_payload():
    # a.txt regression: panel_id lives in get_dashboard's RESULT, not in any
    # prior call's arguments. A unique same-named scalar in a recent artifact
    # must be used to fill the required argument.
    config = _config()
    tools = _RecordingTools()
    llm = _ScriptedLlm('{"action":"call_tool","name":"get_panel_data","arguments":{}}')
    updates = executor_node(
        _state(
            candidate_tools=[_PANEL_DATA_TOOL],
            artifacts=[
                {
                    "tool": "get_dashboard",
                    "step_index": 0,
                    "replan_id": 0,
                    "composite_score": 0.8,
                    "summary": "1 panel",
                    "raw_ref": {"panels": [{"panel_id": 77, "title": "ROWS AVAILABILITY"}]},
                }
            ],
        ),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert tools.calls == [("get_panel_data", {"panel_id": 77})]
    assert any(e.get("step") == "executor.arguments_repaired" for e in updates["events"])


def test_ambiguous_result_values_are_never_guessed():
    config = _config()
    tools = _RecordingTools()
    llm = _ScriptedLlm('{"action":"call_tool","name":"get_panel_data","arguments":{}}')
    updates = executor_node(
        _state(
            candidate_tools=[_PANEL_DATA_TOOL],
            artifacts=[
                {
                    "tool": "search_panels",
                    "step_index": 0,
                    "replan_id": 0,
                    "composite_score": 0.8,
                    "summary": "2 panels",
                    "raw_ref": {"panels": [{"panel_id": 12}, {"panel_id": 99}]},
                }
            ],
        ),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert tools.calls == []  # two candidate values -> no guess, normal invalid path
    assert any(e.get("step") == "executor.tool_args_invalid" for e in updates["events"])


def test_repeated_identical_invalid_call_is_deduped_not_revalidated():
    # a.txt regression: 10 consecutive identical get_panel_data(missing panel_id)
    # turns. The second identical invalid attempt must hit the duplicate guard,
    # not re-fail validation forever.
    config = _config()
    tools = _RecordingTools()
    llm = _ScriptedLlm('{"action":"call_tool","name":"get_panel_data","arguments":{}}')
    first = executor_node(
        _state(candidate_tools=[_PANEL_DATA_TOOL]),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert any(e.get("step") == "executor.tool_args_invalid" for e in first["events"])

    second = executor_node(
        _state(
            candidate_tools=[_PANEL_DATA_TOOL],
            tool_calls=first.get("tool_calls") or [],
            iteration=first["iteration"],
        ),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert any(e.get("step") == "executor.duplicate_tool_skipped" for e in second["events"])
    assert not any(e.get("step") == "executor.tool_args_invalid" for e in second["events"])
    assert tools.calls == []


def test_failed_artifact_does_not_satisfy_required_tool():
    config = _config()
    llm = _ScriptedLlm('{"action":"finish_step"}')
    updates = executor_node(
        _state(
            plan={"goal": "check", "steps": [{"title": "Fetch", "action": "fetch", "required_tools": ["get_panel_data"]}]},
            candidate_tools=[_PANEL_DATA_TOOL],
            artifacts=[
                {
                    "tool": "get_panel_data",
                    "step_index": 0,
                    "replan_id": 0,
                    "raw_ref": {"ok": False, "error": "upstream failed"},
                }
            ],
        ),
        config=config,
        llm=llm,
        tools=_RecordingTools(),
    )

    assert any(e.get("step") == "executor.required_tools_missing" for e in updates["events"])
    assert updates.get("phase") != "fact_extracting"


def test_repaired_duplicate_call_is_deduped():
    # The dedup signature must reflect the REPAIRED arguments, or a repeated
    # empty-args request would re-execute the same repaired call.
    config = _config()
    tools = _RecordingTools()
    llm = _ScriptedLlm('{"action":"call_tool","name":"get_dashboard_tokens","arguments":{}}')
    prior = {
        "name": "get_dashboard",
        "status": "ok",
        "step_index": 0,
        "replan_id": 0,
        "args_preview": '{"name": "autopod_rows_availability"}',
    }
    first = executor_node(
        _state(candidate_tools=[_TOKENS_TOOL], tool_calls=[prior]),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert len(tools.calls) == 1
    second = executor_node(
        _state(
            candidate_tools=[_TOKENS_TOOL],
            tool_calls=(first.get("tool_calls") or []),
            artifacts=first.get("artifacts") or [],
            iteration=first["iteration"],
        ),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert len(tools.calls) == 1  # no second execution
    assert any(e.get("step") == "executor.duplicate_tool_skipped" for e in second["events"])


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


# --- nested tool args + payload failure classification -------------------------


class _NestedPanelTools(ToolProvider):
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def search_tools(self, query: str, *, limit: int = 25, allowlist=None) -> list[ToolCandidate]:
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        return {"ok": True, "row_count": 1, "rows": [{"lab": "RTP11-108"}]}


def test_nested_params_are_flattened_before_panel_data_call():
    config = _config()
    tools = _NestedPanelTools()
    llm = _ScriptedLlm(
        '{"action":"call_tool","name":"get_panel_data","arguments":{'
        '"params":{"panel_id":77,"panel_tokens":{"site":"RTP","availablepowerrange":"Available_Power>30"}},'
        '"panel_id":77}}'
    )
    updates = executor_node(
        _state(candidate_tools=[_PANEL_DATA_TOOL]),
        config=config,
        llm=llm,
        tools=tools,
    )
    assert tools.calls
    _name, args = tools.calls[0]
    assert args["panel_id"] == 77
    assert args["panel_tokens"]["site"] == "RTP"
    assert updates["tool_calls"][-1]["status"] == "ok"


class _OpenFilterRetryTools(ToolProvider):
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def search_tools(self, query: str, *, limit: int = 25, allowlist=None) -> list[ToolCandidate]:
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        if len(self.calls) == 1:
            return {
                "ok": False,
                "error": "open filters",
                "open_filters": ["row"],
                "token_defaults": {"row": "ALL"},
            }
        return {"ok": True, "row_count": 2, "rows": [{"lab": "RTP11-108"}, {"lab": "RTP12-F340"}]}


def test_open_filters_triggers_panel_data_retry_and_marks_first_call_failed():
    config = _config()
    tools = _OpenFilterRetryTools()
    llm = _ScriptedLlm(
        '{"action":"call_tool","name":"get_panel_data","arguments":{"panel_id":77,"panel_tokens":{"site":"RTP"}}}'
    )
    state = _state(
        candidate_tools=[_PANEL_DATA_TOOL],
        artifacts=[
            {
                "tool": "get_dashboard_tokens",
                "step_index": 0,
                "replan_id": 0,
                "composite_score": 0.8,
                "summary": "tokens",
                "raw_ref": {"token_catalog": [{"name": "row", "default": "ALL"}]},
            }
        ],
    )
    updates = executor_node(state, config=config, llm=llm, tools=tools)
    assert len(tools.calls) == 2
    assert tools.calls[1][1]["panel_tokens"]["row"] == "ALL"
    assert any(e.get("step") == "executor.panel_data_retry" for e in updates["events"])
    failed = [c for c in updates["tool_calls"] if c.get("status") == "failed"]
    assert failed
    ok_calls = [c for c in updates["tool_calls"] if c.get("status") == "ok"]
    assert ok_calls
