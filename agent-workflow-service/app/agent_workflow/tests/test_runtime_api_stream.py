from __future__ import annotations

from app.services.agent_workflow.runtime import stream_sse
from app.services.agent_workflow.schema import AgentWorkflowRunRequest


class _FakeEngine:
    class _Cfg:
        name = "fake-agent"

    config = _Cfg()

    def stream(self, request):
        yield {"type": "status", "message": "Planning..."}
        yield {"type": "plan", "goal": "g", "steps": ["s1"], "message": "Plan created"}
        yield {"type": "delta", "content": "hello"}
        yield {
            "type": "done",
            "answer": "hello",
            "review": {"verdict": "APPROVE"},
            "artifact_count": 0,
            "tool_call_count": 0,
            "error": None,
            "thread_id": "t1",
        }


def test_stream_sse_emits_meta_and_done_events(monkeypatch):
    monkeypatch.setattr("app.services.agent_workflow.runtime.resolve_engine", lambda payload: _FakeEngine())
    payload = AgentWorkflowRunRequest(query="test")
    frames = list(stream_sse(payload))
    joined = "".join(frames)
    assert "event: meta" in joined
    assert "event: status" in joined
    assert "event: plan" in joined
    assert "event: delta" in joined
    assert "event: done" in joined
