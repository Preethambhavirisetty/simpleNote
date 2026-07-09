from __future__ import annotations

from app.api.action_controller import _dispatch
from app.api.schema import AgentWorkflowActionRequest


def _req(action: str, **kwargs) -> AgentWorkflowActionRequest:
    payload = {"action": action, "config_name": "default", **kwargs}
    return AgentWorkflowActionRequest(**payload)


def test_config_load_exposes_safe_dict_with_new_fields():
    out = _dispatch(_req("config.load"))
    config = out["config"]
    # safe_dict must exist and surface the newly added policy knobs.
    assert config["policy"]["max_no_progress_turns"] >= 1
    assert "max_fact_chars" in config["policy"]["truncation"]
    assert "max_explore_cycles" in config["policy"]
    # secrets are redacted, never leaked verbatim.
    assert config["llm"]["api_key"] in ("", "***")


def test_config_signature_action_runs():
    out = _dispatch(_req("config.signature"))
    assert out["signature"]
    assert out["config"]["name"]


def test_profile_resolve_action():
    out = _dispatch(_req("profile.resolve", runtime_context={"exploration_profile": "heavy"}))
    assert out["exploration_profile"] == "heavy"


def test_profile_apply_action_merges_preset_under_caller_overrides():
    out = _dispatch(
        _req(
            "profile.apply",
            runtime_context={"exploration_profile": "heavy"},
            input={"overrides": {"policy": {"max_executor_iterations": 1}}},
        )
    )
    assert out["exploration_profile"] == "heavy"
    # caller override wins; unset keys come from the heavy preset.
    assert out["overrides"]["policy"]["max_executor_iterations"] == 1
    assert out["overrides"]["policy"]["max_explore_cycles"] == 3


def test_actions_list_includes_profile_actions():
    out = _dispatch(_req("actions.list"))
    assert "profile.resolve" in out["actions"]
    assert "profile.apply" in out["actions"]
