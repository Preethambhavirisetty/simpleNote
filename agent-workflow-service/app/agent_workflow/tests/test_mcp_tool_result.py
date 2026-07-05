from __future__ import annotations

import json

from app.agent_workflow.config import TruncationPolicy
from app.agent_workflow.context.truncator import truncate_tool_result
from app.agent_workflow.providers.mcp import normalize_mcp_tool_result


def _dashboard(name: str, *, panels: int = 3) -> dict[str, object]:
    return {"name": name, "app": "zabbix_poc", "panel_count": panels}


def test_normalize_prefers_structured_content_result():
    dashboards = [_dashboard("alpha"), _dashboard("beta")]
    raw = {
        "content": [{"type": "text", "text": json.dumps(dashboards[0])}],
        "structuredContent": {"result": dashboards},
    }

    normalized = normalize_mcp_tool_result(raw)

    assert normalized == dashboards


def test_normalize_collects_multiple_content_text_items():
    dashboards = [_dashboard("alpha"), _dashboard("beta"), _dashboard("gamma")]
    raw = {
        "content": [{"type": "text", "text": json.dumps(item)} for item in dashboards],
        "structuredContent": {},
    }

    normalized = normalize_mcp_tool_result(raw)

    assert normalized == dashboards


def test_truncator_lists_many_dashboard_rows_without_hiding_count():
    dashboards = [_dashboard(f"dashboard_{index}", panels=index % 5) for index in range(32)]
    summary, raw_ref, truncated = truncate_tool_result(
        dashboards,
        step_query="list all dashboards",
        policy=TruncationPolicy(max_artifact_chars=8000),
    )

    assert "dashboard_0" in summary
    assert "dashboard_31" in summary
    assert "... and" not in summary
    assert raw_ref == {"type": "list", "total": 32, "truncated": False}
