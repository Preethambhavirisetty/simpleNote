from __future__ import annotations

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
