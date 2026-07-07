from __future__ import annotations

from app.agent_workflow.follow_up import build_search_query
from app.agent_workflow.parsing import parse_plan_markdown


class _NoopLlm:
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return '{"action":"finish_step"}'

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


class _NoopTools:
    def search_tools(self, query: str, *, limit: int = 25, allowlist=None):
        return []

    def call_tool(self, name: str, arguments: dict):
        return {"ok": True}


def test_initial_state_sets_search_query_when_planner_disabled():
    # Finding 2: with the planner disabled the graph skips planner_node, so the
    # deterministic rewrite must be seeded in _initial_state, not only in planner.
    from app.agent_workflow.config import parse_agent_config
    from app.agent_workflow.engine import AgentEngine
    from app.agent_workflow.streaming import HostCallbacks, RunRequest

    config = parse_agent_config(
        {
            "name": "np",
            "prompts_inline": {"planner": "p", "executor": "e", "reviewer": "r"},
            "llm": {"base_url": "http://llm.local/v1", "model": "m"},
            "policy": {"enable_planner": False, "enable_fast_path": False},
        }
    )
    engine = AgentEngine(config=config, llm=_NoopLlm(), tools=_NoopTools(), callbacks=HostCallbacks())
    request = engine._validate_request(
        RunRequest(query="how many are there?", history=[{"role": "user", "content": "show the aiera dashboard"}])
    )
    state = engine._initial_state(request)
    assert "aiera dashboard" in state["search_query"]
    assert "how many are there?" in state["search_query"]


def test_build_search_query_returns_standalone_query_unchanged():
    assert build_search_query("list all Splunk dashboards", []) == "list all Splunk dashboards"


def test_build_search_query_resolves_followup_with_prior_turn():
    history = [
        {"role": "user", "content": "show me the aiera power management dashboard"},
        {"role": "assistant", "content": "Here are its 16 panels..."},
    ]
    rewritten = build_search_query("how many panels are there?", history)
    assert "aiera power management dashboard" in rewritten
    assert "how many panels" in rewritten


def test_build_search_query_ignores_history_for_non_followup():
    history = [{"role": "user", "content": "earlier unrelated question"}]
    # A self-contained request should not get the prior turn stapled on.
    assert build_search_query("create a new report for Q3 revenue", history) == "create a new report for Q3 revenue"


def test_planner_markdown_parses_search_query_section():
    text = (
        "### Search Query\ncount of panels in the aiera power management dashboard\n"
        "### Goal\nAnswer the panel count\n"
        "### Execution Plan\n1. **Fetch** — Action: get dashboard — Tool hint: get_dashboard\n"
        "### Acceptance Criteria\n- panel count reported"
    )
    plan = parse_plan_markdown(text)
    assert plan["search_query"] == "count of panels in the aiera power management dashboard"


def test_planner_markdown_search_query_optional():
    text = "### Goal\nDo the thing\n### Execution Plan\n1. **Step** — Action: do"
    plan = parse_plan_markdown(text)
    assert plan.get("search_query", "") == ""
