from app.agent_workflow.follow_up import resolve_follow_up_policy


def test_listing_follow_up_requires_fresh_recall_even_with_persisted_rows():
    history = [
        {"role": "user", "content": "can you check if i have available power of atleast 30kv in rtp region?"},
        {"role": "assistant", "content": "Yes, multiple rows exceed 30 kW."},
    ]
    artifacts = [
        {
            "tool": "get_panel_data",
            "raw_ref": {
                "ok": True,
                "rows": [{"LAB": "RTP11-108", "ROW": "AA", "Available Power @ 80% (kW)": 82.87}],
                "rows_usable": True,
            },
        }
    ]
    policy = resolve_follow_up_policy(
        query="what rows are available then? list them with their available power",
        history=history,
        persisted_artifacts=artifacts,
        persistence_active=True,
        require_tool_on_follow_up=True,
    )
    assert policy.is_follow_up
    assert policy.require_tool_recall
    assert policy.require_fresh_row_recall


def test_follow_up_tool_recall_requires_get_panel_data_not_tokens():
    from app.agent_workflow.follow_up import apply_follow_up_runtime_context, follow_up_tool_recall_missing

    policy = resolve_follow_up_policy(
        query="what rows are available then? list them with their available power",
        history=[
            {"role": "user", "content": "can you check if i have available power of atleast 30kv in rtp region?"},
            {"role": "assistant", "content": "Yes, multiple rows exceed 30 kW."},
        ],
        persisted_artifacts=[
            {
                "tool": "get_panel_data",
                "raw_ref": {
                    "ok": True,
                    "rows": [{"LAB": "RTP11-108", "ROW": "AA", "Available Power @ 80% (kW)": 82.87}],
                    "rows_usable": True,
                },
            }
        ],
        persistence_active=True,
        require_tool_on_follow_up=True,
    )
    state = {
        "runtime_context": apply_follow_up_runtime_context({}, policy),
        "tool_calls": [{"name": "get_dashboard_tokens", "status": "ok"}],
        "artifacts": [],
    }
    gaps = follow_up_tool_recall_missing(state)
    assert gaps
    assert "get_panel_data" in gaps[0]


def test_presentation_follow_up_can_reuse_usable_rows():
    history = [
        {"role": "user", "content": "is there at least 30 kW in RTP?"},
        {"role": "assistant", "content": "Yes."},
    ]
    artifacts = [
        {
            "tool": "get_panel_data",
            "raw_ref": {
                "ok": True,
                "rows": [{"ROW": "AA", "Available Power @ 80% (kW)": 82.87}],
                "rows_usable": True,
            },
        }
    ]
    policy = resolve_follow_up_policy(
        query="put that answer in a markdown table",
        history=history,
        persisted_artifacts=artifacts,
        persistence_active=True,
        require_tool_on_follow_up=True,
    )
    assert policy.is_follow_up
    assert not policy.require_tool_recall
