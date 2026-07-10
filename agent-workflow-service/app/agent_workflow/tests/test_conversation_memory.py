from __future__ import annotations

import json
from pathlib import Path

from app.agent_workflow.config import AgentConfig, AgentPolicy, LlmConfig, McpConfig, TruncationPolicy
from app.agent_workflow.context.builder import ContextBuilder
from app.agent_workflow.conversation_memory import (
    ConversationMemoryStore,
    extract_memory_slots,
    render_memory,
)
from app.agent_workflow.state import AgentState


def _state(tool_calls, artifacts=None, runtime=None):
    state: AgentState = {
        "tool_calls": tool_calls,
        "artifacts": artifacts or [],
    }
    if runtime is not None:
        state["runtime_context"] = runtime
    return state


def test_store_round_trip_in_process():
    store = ConversationMemoryStore(url="")  # no Redis -> in-process backend
    assert store.uses_redis is False
    assert store.load("s1") == {}
    store.save("s1", {"dashboard": {"value": "aiera_power", "turn": 1}}, ttl_seconds=100)
    assert store.load("s1") == {"dashboard": {"value": "aiera_power", "turn": 1}}
    store.delete("s1")
    assert store.load("s1") == {}


def test_parse_args_recovers_entities_from_truncated_preview():
    # args_preview is a length-capped JSON string; a call with large args
    # serializes to invalid JSON. Slots must still be recovered from the head.
    import app.agent_workflow.conversation_memory as cm

    full = json.dumps({"dashboard": "autopod_rows_availability", "query": "x" * 400})
    truncated = full[:300]  # invalid JSON mid-string
    recovered = cm._parse_args(truncated)
    assert recovered.get("dashboard") == "autopod_rows_availability"


def test_local_store_evicts_oldest_over_cap():
    import app.agent_workflow.conversation_memory as cm

    store = ConversationMemoryStore(url="")
    original = cm._MAX_LOCAL_SESSIONS
    cm._MAX_LOCAL_SESSIONS = 3
    try:
        for i in range(5):
            store.save(f"s{i}", {"k": {"value": str(i), "turn": 1}}, ttl_seconds=60)
        assert len(store._local) == 3
        assert "s0" not in store._local and "s4" in store._local  # FIFO eviction
    finally:
        cm._MAX_LOCAL_SESSIONS = original


def test_extract_captures_entity_from_successful_tool_call():
    calls = [
        {"name": "get_dashboard", "status": "ok", "step_index": 0,
         "args_preview": json.dumps({"dashboard": "aiera_power"})},
    ]
    artifacts = [{"tool": "get_dashboard", "step_index": 0, "summary": "16 panels\nCPU, memory"}]
    memory = extract_memory_slots({}, _state(calls, artifacts), turn=1, max_slots=10)
    assert memory["dashboard"]["value"] == "aiera_power"
    assert memory["dashboard"]["finding"] == "16 panels"


def test_extract_skips_freeform_and_failed_calls():
    calls = [
        {"name": "search", "status": "ok", "args_preview": json.dumps({"query": "how many panels", "index": "main"})},
        {"name": "get_dashboard", "status": "error", "args_preview": json.dumps({"dashboard": "ghost"})},
    ]
    memory = extract_memory_slots({}, _state(calls), turn=2, max_slots=10)
    assert "query" not in memory          # free-text arg is not a stable entity
    assert "dashboard" not in memory      # failed call contributes nothing
    assert memory["index"]["value"] == "main"


def test_extract_last_write_wins_and_caps_slots():
    prior = {"a": {"value": "1", "turn": 1}, "b": {"value": "2", "turn": 1}, "c": {"value": "3", "turn": 1}}
    calls = [{"name": "t", "status": "ok", "args_preview": json.dumps({"d": "4", "a": "updated"})}]
    memory = extract_memory_slots(prior, _state(calls), turn=5, max_slots=2)
    assert len(memory) == 2                       # capped to most recently touched
    assert memory["a"]["value"] == "updated"      # last-write-wins
    assert "d" in memory
    assert "b" not in memory and "c" not in memory  # oldest evicted


def test_extract_merges_caller_preferences():
    memory = extract_memory_slots(
        {}, _state([], runtime={"conversation_memory": {"region": "us-east-1"}}), turn=1, max_slots=10
    )
    assert memory["region"]["value"] == "us-east-1"
    assert memory["region"]["tool"] == "caller"


def test_render_memory_most_recent_first():
    memory = {
        "index": {"value": "main", "turn": 1},
        "dashboard": {"value": "aiera_power", "turn": 3, "finding": "16 panels"},
    }
    rendered = render_memory(memory)
    lines = rendered.splitlines()
    assert lines[0] == "- dashboard = aiera_power (16 panels)"
    assert lines[1] == "- index = main"


def _builder_config():
    return AgentConfig(
        name="test",
        prompts={},
        llm=LlmConfig(base_url="http://localhost:8001/v1", api_key="FAKE", model="LOCAL"),
        mcp=McpConfig(),
        policy=AgentPolicy(truncation=TruncationPolicy()),
        base_dir=Path(__file__).resolve().parents[1],
    )


def test_context_builder_injects_memory_only_on_follow_up():
    builder = ContextBuilder(_builder_config())
    base_state: AgentState = {
        "user_query": "how many panels does it have?",
        "plan": {"goal": "answer", "steps": [{"title": "S", "action": "a"}]},
        "conversation_memory": {"dashboard": {"value": "aiera_power", "turn": 1, "finding": "16 panels"}},
        "runtime_context": {},
    }
    fresh = "\n".join(m["content"] for m in builder.build(base_state, "planner"))
    assert "aiera_power" not in fresh  # new topic: memory withheld to avoid bleed

    base_state["runtime_context"] = {"follow_up": True}
    follow_up = "\n".join(m["content"] for m in builder.build(base_state, "planner"))
    assert "Conversation memory" in follow_up
    assert "dashboard = aiera_power (16 panels)" in follow_up


def test_memory_cleared_on_new_topic(monkeypatch):
    from app.agent_workflow import engine as engine_mod
    from app.agent_workflow.engine import AgentEngine
    from app.agent_workflow.streaming import HostCallbacks, RunRequest

    class _NoopLlm:
        def complete(self, messages, *, max_tokens: int = 1024) -> str:
            return "{}"

        def stream(self, messages, *, max_tokens: int = 1024):
            yield "{}"

    config = _builder_config()
    eng = AgentEngine(config=config, llm=_NoopLlm(), tools=None, callbacks=HostCallbacks())

    class _Store:
        def __init__(self):
            self.data = {"s1": {"dashboard": {"value": "aiera_power", "turn": 1}}}

        def load(self, session_id):
            return dict(self.data.get(session_id) or {})

        def delete(self, session_id):
            self.data.pop(session_id, None)

        def save(self, session_id, slots, *, ttl_seconds):
            self.data[session_id] = dict(slots)

    store = _Store()
    monkeypatch.setattr(engine_mod, "get_memory_store", lambda: store)

    history = [{"role": "user", "content": "list dashboards"}, {"role": "assistant", "content": "done"}]

    _req, _ = eng._prepare_session(
        RunRequest(query="what is the error rate for payments", session_id="s1", history=history)
    )
    cleared = eng._clear_conversation_memory_if_new_topic(
        session_id="s1",
        is_follow_up=bool((_req.runtime_context or {}).get("follow_up")),
        thread_id="t1",
    )
    assert cleared is not None
    assert cleared["label"] == "memory.cleared"
    assert cleared["cleared_slots"] == ["dashboard"]
    assert store.load("s1") == {}

    store.data["s1"] = {"dashboard": {"value": "aiera_power", "turn": 1}}
    _req2, _ = eng._prepare_session(
        RunRequest(query="how many panels does it have?", session_id="s1", history=history)
    )
    assert eng._clear_conversation_memory_if_new_topic(
        session_id="s1",
        is_follow_up=bool((_req2.runtime_context or {}).get("follow_up")),
        thread_id="t2",
    ) is None
    assert store.load("s1")["dashboard"]["value"] == "aiera_power"


def test_memory_not_cleared_on_power_refinement_follow_up(monkeypatch):
    from app.agent_workflow import engine as engine_mod
    from app.agent_workflow.engine import AgentEngine
    from app.agent_workflow.streaming import HostCallbacks, RunRequest

    class _NoopLlm:
        def complete(self, messages, *, max_tokens: int = 1024) -> str:
            return "{}"

        def stream(self, messages, *, max_tokens: int = 1024):
            yield "{}"

    config = _builder_config()
    eng = AgentEngine(config=config, llm=_NoopLlm(), tools=None, callbacks=HostCallbacks())

    class _Store:
        def __init__(self):
            self.data = {
                "s1": {
                    "dashboard": {"value": "autopod_rows_availability", "turn": 1},
                    "site": {"value": "RTP", "turn": 1},
                }
            }

        def load(self, session_id):
            return dict(self.data.get(session_id) or {})

        def delete(self, session_id):
            self.data.pop(session_id, None)

        def save(self, session_id, slots, *, ttl_seconds):
            self.data[session_id] = dict(slots)

    store = _Store()
    monkeypatch.setattr(engine_mod, "get_memory_store", lambda: store)

    history = [
        {
            "role": "user",
            "content": "autopod_rows_availability, site=RTP, show rows with available power under 30 kW",
        },
        {"role": "assistant", "content": "There is no single less-than-30 bucket; closest filters are ..."},
    ]
    follow_up = (
        "if there is no explicit filter for less than 30, "
        "give me all rows from all from 0 to under 30"
    )
    req, _ = eng._prepare_session(RunRequest(query=follow_up, session_id="s1", history=history))
    assert (req.runtime_context or {}).get("follow_up") is True
    assert eng._clear_conversation_memory_if_new_topic(
        session_id="s1",
        is_follow_up=bool((req.runtime_context or {}).get("follow_up")),
        thread_id="t-power",
    ) is None
    assert store.load("s1")["dashboard"]["value"] == "autopod_rows_availability"


def test_memory_cleared_activity_event_survives_sse_whitelist():
    from app.api.sse_adapter import engine_event_to_sse

    name, data = engine_event_to_sse(
        {
            "type": "agent_activity",
            "label": "memory.cleared",
            "slot_count": 2,
            "cleared_slots": ["dashboard", "site"],
            "thread_id": "t",
        }
    )
    assert name == "agent_activity"
    assert data["label"] == "memory.cleared"
    assert data["slot_count"] == 2
    assert data["cleared_slots"] == ["dashboard", "site"]


def test_memory_activity_event_survives_sse_whitelist():
    # The memory.updated activity fields must survive the SSE field whitelist so
    # the UI can show what was remembered this turn.
    from app.api.sse_adapter import engine_event_to_sse

    name, data = engine_event_to_sse(
        {
            "type": "agent_activity",
            "label": "memory.updated",
            "slot_count": 2,
            "updated_slots": ["dashboard=aiera_power"],
            "thread_id": "t",
        }
    )
    assert name == "agent_activity"
    assert data["label"] == "memory.updated"
    assert data["slot_count"] == 2
    assert data["updated_slots"] == ["dashboard=aiera_power"]
