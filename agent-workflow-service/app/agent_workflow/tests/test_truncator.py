from __future__ import annotations

from app.agent_workflow.config import TruncationPolicy
from app.agent_workflow.context.truncator import truncate_tool_result


def test_truncator_marks_large_lists():
    rows = [{"id": i, "text": f"row-{i}"} for i in range(20)]
    summary, _raw, truncated = truncate_tool_result(
        {"items": rows, "total": 20},
        step_query="search documents",
        policy=TruncationPolicy(max_artifact_chars=5000),
    )
    assert truncated is True
    assert "items" in summary or "total" in summary
