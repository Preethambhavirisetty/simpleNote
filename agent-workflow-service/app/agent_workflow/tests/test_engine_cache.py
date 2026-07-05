from __future__ import annotations

from app.agent_workflow import clear_engine_caches
from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.streaming import HostCallbacks


def _config() -> dict:
    return {
        "name": "cached-agent",
        "prompts": {"planner": "planner", "executor": "executor", "reviewer": "reviewer"},
        "llm": {"base_url": "http://localhost:8000/v1", "model": "dummy-model"},
        "mcp": {},
        "policy": {},
    }


def test_from_dict_reuses_cached_graph_and_providers():
    clear_engine_caches()
    first = AgentEngine.from_dict(_config(), callbacks=HostCallbacks())
    second = AgentEngine.from_dict(_config(), callbacks=HostCallbacks())

    assert first.llm is second.llm
    assert first.tools is second.tools
    assert first.graph is second.graph


def test_signature_change_breaks_cache_reuse():
    clear_engine_caches()
    first = AgentEngine.from_dict(_config(), callbacks=HostCallbacks())
    modified = _config()
    modified["policy"] = {"planner": {"enabled": False}}
    second = AgentEngine.from_dict(modified, callbacks=HostCallbacks())
    assert first.graph is not second.graph
