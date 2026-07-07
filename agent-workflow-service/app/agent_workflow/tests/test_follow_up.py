from __future__ import annotations

from app.agent_workflow.follow_up import (
    apply_follow_up_runtime_context,
    follow_up_approval_gaps,
    follow_up_tool_recall_missing,
    is_follow_up_query,
    resolve_follow_up_policy,
)


def test_follow_up_query_detects_table_request():
    history = [{"role": "assistant", "content": "Here are all dashboards..."}]
    assert is_follow_up_query("put them in a table with serial numbers", history)


def test_without_persistence_follow_up_requires_tool_recall():
    history = [{"role": "assistant", "content": "Here are dashboards..."}]
    policy = resolve_follow_up_policy(
        query="put them in a table",
        history=history,
        persisted_artifacts=[],
        persistence_active=False,
        require_tool_on_follow_up=True,
    )
    assert policy.is_follow_up
    assert policy.require_tool_recall
    runtime = apply_follow_up_runtime_context({}, policy)
    assert runtime["require_tools"] is True
    assert runtime["follow_up"] is True


def test_with_persisted_artifacts_follow_up_does_not_require_recall():
    history = [{"role": "assistant", "content": "Here are dashboards..."}]
    artifacts = [{"tool": "list_dashboards", "summary": "32 dashboards", "raw_ref": {"items": []}}]
    policy = resolve_follow_up_policy(
        query="put them in a table",
        history=history,
        persisted_artifacts=artifacts,
        persistence_active=True,
        require_tool_on_follow_up=True,
    )
    assert policy.is_follow_up
    assert not policy.require_tool_recall
    runtime = apply_follow_up_runtime_context({}, policy)
    assert "require_tools" not in runtime


def test_follow_up_executor_blocks_finish_without_tool_evidence():
    state = {
        "runtime_context": {
            "follow_up": True,
            "require_tools": True,
            "follow_up_required_tools": ["list_dashboards"],
        },
        "artifacts": [],
        "tool_calls": [],
    }
    missing = follow_up_tool_recall_missing(state)
    assert missing
    assert "list_dashboards" in missing[0]


def test_follow_up_reviewer_rejects_ungrounded_answer():
    state = {
        "runtime_context": {
            "follow_up": True,
            "require_tools": True,
            "follow_up_required_tools": ["list_dashboards"],
        },
        "artifacts": [],
        "tool_calls": [],
        "draft_answer": "Here is a table...",
    }
    gaps = follow_up_approval_gaps(state)
    assert gaps
