from app.agent_workflow.evidence_grade import artifact_has_row_level_data
from app.agent_workflow.tool_arguments import (
    build_panel_data_retry_arguments,
    classify_tool_result_failure,
    normalize_tool_arguments,
)


def test_normalize_flattens_params_and_panel_tokens():
    args = {
        "params": {
            "panel_id": 77,
            "panel_tokens": {"site": "RTP", "availablepowerrange": "Available_Power>30"},
        },
        "panel_id": 77,
    }
    flat = normalize_tool_arguments(args)
    assert flat["panel_id"] == 77
    assert flat["panel_tokens"]["site"] == "RTP"
    assert flat["panel_tokens"]["availablepowerrange"] == "Available_Power>30"


def test_normalize_merges_parameters_wrapper():
    args = {
        "parameters": {"panel_tokens": {"row": "ALL"}},
        "panel_tokens": {"site": "RTP"},
    }
    flat = normalize_tool_arguments(args)
    assert flat["panel_tokens"]["row"] == "ALL"
    assert flat["panel_tokens"]["site"] == "RTP"


def test_classify_ok_false_with_open_filters():
    reason = classify_tool_result_failure(
        {"ok": False, "error": "open filters", "open_filters": ["row", "labs"]}
    )
    assert reason is not None
    assert "open filters" in reason
    assert "row" in reason


def test_build_panel_data_retry_fills_open_row_from_defaults():
    state = {
        "artifacts": [
            {
                "tool": "get_dashboard_tokens",
                "raw_ref": {
                    "token_catalog": [
                        {"name": "row", "default": "ALL", "values": ["ALL", "RTP11-108"]},
                    ]
                },
            }
        ]
    }
    args = {"panel_id": 77, "panel_tokens": {"site": "RTP"}}
    result = {
        "ok": False,
        "open_filters": ["row"],
        "token_defaults": {"row": "ALL"},
        "error": "open filters",
    }
    retry = build_panel_data_retry_arguments(state, args, result)
    assert retry is not None
    assert retry["panel_tokens"]["row"] == "ALL"
    assert retry["panel_tokens"]["site"] == "RTP"


def test_ok_false_artifact_is_not_row_level():
    assert not artifact_has_row_level_data({"raw_ref": {"ok": False, "open_filters": ["row"]}})
