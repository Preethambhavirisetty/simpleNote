from __future__ import annotations

import pytest

from app.agent_workflow.runtime_schema import AgentConfigModel, RunRequestModel


def test_agent_config_model_rejects_unknown_keys():
    with pytest.raises(Exception):
        AgentConfigModel.model_validate(
            {
                "name": "x",
                "prompts": {"planner": "prompts/planner.md"},
                "llm": {"base_url": "http://localhost:8000/v1", "model": "m"},
                "unknown": True,
            }
        )


def test_reviewer_max_cycles_zero_is_rejected():
    # An enabled reviewer always runs once; 0 is ambiguous, so it is rejected.
    # Disable review via reviewer.enabled/enable_reviewer instead.
    base = {
        "name": "x",
        "prompts": {"planner": "prompts/planner.md"},
        "llm": {"base_url": "http://localhost:8000/v1", "model": "m"},
    }
    with pytest.raises(Exception):
        AgentConfigModel.model_validate({**base, "policy": {"reviewer": {"max_cycles": 0}}})
    with pytest.raises(Exception):
        AgentConfigModel.model_validate({**base, "policy": {"max_review_cycles": 0}})


def test_run_request_model_blocks_prototype_pollution_keys():
    with pytest.raises(Exception):
        RunRequestModel.model_validate(
            {
                "query": "hi",
                "runtime_context": {"__proto__": {"polluted": True}},
            }
        )
