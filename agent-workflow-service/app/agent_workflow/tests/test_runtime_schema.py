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


def test_run_request_model_blocks_prototype_pollution_keys():
    with pytest.raises(Exception):
        RunRequestModel.model_validate(
            {
                "query": "hi",
                "runtime_context": {"__proto__": {"polluted": True}},
            }
        )
