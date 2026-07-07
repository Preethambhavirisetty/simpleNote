from __future__ import annotations

from app.agent_workflow.follow_up import build_search_query
from app.agent_workflow.parsing import parse_plan_markdown


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
