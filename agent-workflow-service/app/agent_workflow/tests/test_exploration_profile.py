from __future__ import annotations

import pytest

from app.agent_workflow.exploration_profile import (
    apply_exploration_profile_to_overrides,
    normalize_exploration_profile,
    profile_policy_overrides,
    resolve_exploration_profile,
    validate_runtime_context_profile,
)
from app.agent_workflow.config import merge_agent_config, load_agent_config
from pathlib import Path


def test_normalize_exploration_profile_aliases():
    assert normalize_exploration_profile("heavy-explore") == "heavy"
    assert normalize_exploration_profile("quick-read") == "quick"
    assert normalize_exploration_profile("invalid") is None


def test_resolve_exploration_profile_request_beats_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_EXPLORATION_PROFILE", "heavy")
    assert resolve_exploration_profile({"exploration_profile": "quick"}) == "quick"
    assert resolve_exploration_profile({}) == "heavy"


def test_resolve_exploration_profile_defaults_to_quick(monkeypatch):
    monkeypatch.delenv("DEFAULT_EXPLORATION_PROFILE", raising=False)
    assert resolve_exploration_profile({}) == "quick"


def test_profile_policy_overrides_heavy_has_higher_caps():
    heavy = profile_policy_overrides("heavy")["policy"]
    quick = profile_policy_overrides("quick")["policy"]
    assert heavy["max_explore_cycles"] > quick["max_explore_cycles"]
    assert heavy["max_executor_iterations"] > quick["max_executor_iterations"]
    assert heavy["reviewer"]["mode"] == "always"
    assert quick["reviewer"]["mode"] == "on_risk"


def test_apply_exploration_profile_to_overrides_merges_policy():
    overrides = {"policy": {"max_executor_iterations": 1}}
    mode = apply_exploration_profile_to_overrides(overrides, {"exploration_profile": "heavy"})
    assert mode == "heavy"
    assert overrides["policy"]["max_executor_iterations"] == 20
    assert overrides["policy"]["max_explore_cycles"] == 3


def test_validate_runtime_context_profile_rejects_invalid():
    with pytest.raises(ValueError, match="exploration_profile"):
        validate_runtime_context_profile({"exploration_profile": "turbo"})


def test_heavy_profile_changes_config_signature():
    base = {
        "name": "t",
        "prompts_inline": {"planner": "p", "executor": "e", "reviewer": "r"},
        "llm": {"base_url": "http://llm.local/v1", "model": "m"},
        "policy": {},
    }
    quick_overrides = {}
    heavy_overrides = {}
    apply_exploration_profile_to_overrides(quick_overrides, {"exploration_profile": "quick"})
    apply_exploration_profile_to_overrides(heavy_overrides, {"exploration_profile": "heavy"})
    config_path = Path(__file__).resolve().parents[1] / "agents" / "default.yaml"
    base_cfg = load_agent_config(config_path)
    quick_cfg = merge_agent_config(base_cfg, quick_overrides)
    heavy_cfg = merge_agent_config(base_cfg, heavy_overrides)
    assert quick_cfg.signature() != heavy_cfg.signature()
