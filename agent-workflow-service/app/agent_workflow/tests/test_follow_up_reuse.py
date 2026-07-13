from __future__ import annotations

"""Follow-up evidence-reuse path: a follow-up whose session already holds the
evidence answers via fact_extractor->synthesizer->reviewer without replanning
or re-running tools (the analysis: re-asking about dashboard A must not redo
the full activity)."""

from app.agent_workflow.artifact_store import CrossTurnArtifactStore, get_artifact_store, is_cross_turn_persistence_active
from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.graph import route_after_start
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider
from app.agent_workflow.streaming import RunRequest


def test_route_after_start_supports_fact_extractor_entry():
    assert route_after_start({"phase": "fact_extracting"}) == "fact_extractor"
    assert route_after_start({"phase": "executing"}) == "executor"
    assert route_after_start({"phase": "planning"}) == "planner"
    assert route_after_start({}) == "planner"


def test_artifact_store_in_process_fallback_round_trip():
    store = CrossTurnArtifactStore(url="")
    assert store.available is False  # no Redis
    store.save("sess-x", [{"tool": "get_dashboard", "summary": "16 panels"}], ttl_seconds=60)
    assert store.load("sess-x") == [{"tool": "get_dashboard", "summary": "16 panels"}]
    store.delete("sess-x")
    assert store.load("sess-x") == []


def test_persistence_active_without_redis():
    # Activation is the config flag alone now; the in-process fallback backs it.
    assert is_cross_turn_persistence_active(enabled=True) is True
    assert is_cross_turn_persistence_active(enabled=False) is False


class _ReuseLlm(LlmProvider):
    """Synthesizer gets prose; reviewer gets an APPROVE verdict."""

    def __init__(self):
        self.calls: list[str] = []

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        system = str(messages[0].get("content") or "")
        if "reviewer" in system.lower() or "judge" in system.lower():
            self.calls.append("reviewer")
            return '{"verdict":"APPROVE","issues":[],"missing_evidence":[],"required_changes":[]}'
        self.calls.append("other")
        return "## Dashboard A\nIt has 16 panels (source: get_dashboard)."

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


class _NoToolsExpected(ToolProvider):
    def __init__(self):
        self.searches: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    def search_tools(self, query: str, *, limit: int = 25, allowlist=None) -> list[ToolCandidate]:
        self.searches.append(query)
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"ok": True}


def test_follow_up_with_persisted_evidence_skips_planning_and_tools():
    engine = AgentEngine.from_dict(
        {
            "name": "reuse-test",
            "prompts_inline": {"planner": "plan", "executor": "exec", "reviewer": "judge the draft"},
            "llm": {"base_url": "http://llm.local/v1", "model": "m"},
            "policy": {
                "enable_fast_path": False,
                "cross_turn_artifact_persistence": True,
                "enable_follow_up_reuse": True,
            },
        },
        llm=_ReuseLlm(),
        tools=_NoToolsExpected(),
    )
    session = "reuse-sess-unique-1"
    # Turn 1's evidence, persisted (in-process fallback; no Redis needed).
    get_artifact_store().save(
        session,
        [
            {
                "tool": "get_dashboard",
                "summary": "dashboard A: 16 panels",
                "composite_score": 0.9,
                "raw_ref": {"type": "list", "total": 16},
                "source_ref": {"dashboard": "A"},
            }
        ],
        ttl_seconds=300,
    )

    tools = engine.tools
    result = engine.run(
        RunRequest(
            query="can you check the same dashboard A panels once more just to be sure?",
            session_id=session,
            history=[
                {"role": "user", "content": "tell me about dashboard A panels"},
                {"role": "assistant", "content": "Dashboard A has 16 panels."},
            ],
        )
    )

    assert any(e.get("step") == "router.follow_up_reuse" for e in result.events), result.events
    # No planner/executor activity: no executor turns, no tool work re-done.
    assert not any(str(e.get("step", "")).startswith("executor.") for e in result.events)
    assert tools.searches == [] and tools.calls == []
    assert result.answer
    assert (result.review or {}).get("verdict") == "APPROVE"


def test_new_topic_does_not_take_reuse_path():
    engine = AgentEngine.from_dict(
        {
            "name": "reuse-test-2",
            "prompts_inline": {"planner": "plan", "executor": "exec", "reviewer": "judge the draft"},
            "llm": {"base_url": "http://llm.local/v1", "model": "m"},
            "policy": {
                "enable_fast_path": False,
                "cross_turn_artifact_persistence": True,
                "enable_follow_up_reuse": True,
                "max_executor_iterations": 1,
                "reviewer": {"enabled": False},
            },
        },
        llm=_ReuseLlm(),
        tools=_NoToolsExpected(),
    )
    session = "reuse-sess-unique-2"
    get_artifact_store().save(session, [{"tool": "get_dashboard", "summary": "old topic"}], ttl_seconds=300)

    result = engine.run(
        RunRequest(
            query="completely unrelated brand new subject with no shared anchors",
            session_id=session,
            history=[{"role": "user", "content": "tell me about dashboard A panels"}],
        )
    )
    # New topic: no reuse shortcut, and prior-topic artifacts are not inherited.
    assert not any(e.get("step") == "router.follow_up_reuse" for e in result.events)
