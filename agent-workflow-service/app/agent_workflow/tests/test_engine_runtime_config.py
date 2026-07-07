from __future__ import annotations

from app.agent_workflow.config import parse_agent_config
from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.streaming import HostCallbacks


class NoopLlm(LlmProvider):
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return '{"action":"draft_answer","answer":"ok"}'

    def stream(self, messages, *, max_tokens: int = 1024):
        yield "ok"


class NoopTools(ToolProvider):
    def search_tools(self, query: str, *, limit: int = 25):
        return []

    def call_tool(self, name: str, arguments: dict):
        return {"ok": True}


def _base_config() -> dict:
    return {
        "name": "runtime-agent",
        "prompts": {"planner": "planner text", "executor": "executor text", "reviewer": "reviewer text"},
        "llm": {"base_url": "http://localhost:8000/v1", "model": "dummy-model"},
        "mcp": {},
        "policy": {"enable_planner": True, "enable_reviewer": True},
    }


def test_from_dict_accepts_inline_prompts_and_policy():
    raw = _base_config()
    raw["prompts_inline"] = {"planner": "INLINE PLANNER"}
    engine = AgentEngine.from_dict(raw, llm=NoopLlm(), tools=NoopTools(), callbacks=HostCallbacks())
    assert engine.config.prompt_text("planner") == "INLINE PLANNER"
    assert engine.config.policy.enable_planner is True


def test_from_runtime_config_merges_runtime_overrides():
    engine = AgentEngine.from_runtime_config(
        _base_config(),
        {
            "prompts_inline": {"reviewer": "INLINE REVIEWER"},
            "policy": {"planner": {"enabled": False}},
        },
        llm=NoopLlm(),
        tools=NoopTools(),
        callbacks=HostCallbacks(),
    )
    assert engine.config.prompt_text("reviewer") == "INLINE REVIEWER"
    assert engine.config.policy.enable_planner is False


def test_from_runtime_config_honors_flat_enable_override():
    # A flat runtime override must survive the merge/re-parse: the base config's
    # nested enabled must not silently win over enable_planner: false.
    engine = AgentEngine.from_runtime_config(
        _base_config(),
        {"policy": {"enable_planner": False, "enable_reviewer": False}},
        llm=NoopLlm(),
        tools=NoopTools(),
        callbacks=HostCallbacks(),
    )
    assert engine.config.policy.enable_planner is False
    assert engine.config.policy.enable_reviewer is False
    assert engine.config.policy.planner.enabled is False
    assert engine.config.policy.reviewer.enabled is False


def test_from_runtime_config_honors_flat_max_review_cycles_override():
    # Flat max_review_cycles override must survive merge/re-parse, not be
    # clobbered by the base config's serialized nested max_cycles.
    engine = AgentEngine.from_runtime_config(
        _base_config(),
        {"policy": {"max_review_cycles": 1}},
        llm=NoopLlm(),
        tools=NoopTools(),
        callbacks=HostCallbacks(),
    )
    assert engine.config.policy.max_review_cycles == 1
    assert engine.config.policy.reviewer.max_cycles == 1


def _policy(policy: dict) -> dict:
    return {
        "name": "flags",
        "prompts_inline": {"planner": "p", "executor": "e", "reviewer": "r"},
        "llm": {"base_url": "http://llm.local/v1", "model": "m"},
        "policy": policy,
    }


def test_flat_enable_flags_are_honored_without_nested_objects():
    # The flat enable_* flags must take effect on their own; previously the
    # nested planner/reviewer defaults (enabled=True) silently overrode them.
    config = parse_agent_config(_policy({"enable_planner": False, "enable_reviewer": False}))
    assert config.policy.enable_planner is False
    assert config.policy.enable_reviewer is False
    assert config.policy.planner.enabled is False
    assert config.policy.reviewer.enabled is False


def test_nested_enabled_overrides_flat_flag():
    # When both are set, the nested object wins.
    config = parse_agent_config(
        _policy({"enable_planner": False, "planner": {"enabled": True}})
    )
    assert config.policy.enable_planner is True
    assert config.policy.planner.enabled is True


def test_enable_flags_default_true_when_unset():
    config = parse_agent_config(_policy({}))
    assert config.policy.enable_planner is True
    assert config.policy.enable_reviewer is True


def test_flat_max_review_cycles_is_honored_without_nested():
    # The flat alias must take effect on its own; previously the nested
    # max_cycles default (2) silently overrode it.
    config = parse_agent_config(_policy({"max_review_cycles": 1}))
    assert config.policy.max_review_cycles == 1
    assert config.policy.reviewer.max_cycles == 1


def test_nested_max_cycles_overrides_flat_review_cycles():
    config = parse_agent_config(_policy({"max_review_cycles": 1, "reviewer": {"max_cycles": 3}}))
    assert config.policy.max_review_cycles == 3
    assert config.policy.reviewer.max_cycles == 3


def test_review_cycles_default_when_unset():
    config = parse_agent_config(_policy({}))
    assert config.policy.max_review_cycles == 2
    assert config.policy.reviewer.max_cycles == 2
