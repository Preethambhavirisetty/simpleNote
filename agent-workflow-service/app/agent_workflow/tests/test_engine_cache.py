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



class _Closable:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_provider_cache_closes_evicted_and_cleared_entries(monkeypatch):
    from app.agent_workflow import cache

    clear_engine_caches()
    monkeypatch.setattr(cache, "_MAX_PROVIDER_ENTRIES", 2)

    first = cache.get_or_create_provider("sig-1", "llm", _Closable)
    second = cache.get_or_create_provider("sig-2", "llm", _Closable)
    third = cache.get_or_create_provider("sig-3", "llm", _Closable)

    assert first.closed is True
    assert second.closed is False
    assert third.closed is False

    clear_engine_caches()
    assert second.closed is True
    assert third.closed is True
