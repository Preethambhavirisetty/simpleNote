from __future__ import annotations

from app.agent_workflow.config import TruncationPolicy
from app.agent_workflow.context.truncator import truncate_tool_result


def test_truncator_marks_large_lists():
    rows = [{"id": i, "text": "x" * 400} for i in range(20)]
    summary, _raw, truncated = truncate_tool_result(
        {"items": rows, "total": 20},
        step_query="search documents",
        policy=TruncationPolicy(max_artifact_chars=5000),
    )
    assert truncated is True
    assert "items" in summary or "total" in summary


def test_truncator_keeps_all_dashboard_panels_within_budget():
    panels = [
        {"id": index, "title": f"Panel {index}", "dashboard": "aiera_power_management_demo"}
        for index in range(16)
    ]
    summary, raw_ref, truncated = truncate_tool_result(
        {"found": True, "panels": panels},
        step_query="list all panels in aiera_power_management_demo",
        policy=TruncationPolicy(max_artifact_chars=6000),
    )

    assert truncated is False
    assert '"Panel 0"' in summary or "Panel 0" in summary
    assert '"Panel 15"' in summary or "Panel 15" in summary
    assert "panels_truncated" not in summary
    assert raw_ref.get("panels_count") == 16
