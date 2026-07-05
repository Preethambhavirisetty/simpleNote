from __future__ import annotations

from app.agent_workflow.config import TruncationPolicy
from app.agent_workflow.context.scorer import score_artifact


def test_actionability_prefers_ids():
    scores = score_artifact(
        summary="doc 123 updated",
        step_query="update document",
        tool_result={"ok": True, "doc_id": "123", "rows": [{"a": 1}]},
        existing_artifacts=[],
        policy=TruncationPolicy(),
    )
    assert scores["actionability"] >= 0.7
    assert scores["composite"] > 0.3
