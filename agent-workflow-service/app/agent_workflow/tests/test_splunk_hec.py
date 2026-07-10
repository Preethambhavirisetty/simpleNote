from __future__ import annotations

import json

from app.agent_workflow.splunk_hec import (
    SplunkHecConfig,
    SplunkHecSink,
    build_step_record,
    get_splunk_sink,
    reset_splunk_sink,
)


class _FakeResponse:
    def __init__(self, status_code=200, text="{}"):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    def __init__(self, status_code=200):
        self.posts: list[dict] = []
        self._status = status_code

    def post(self, url, *, content, headers):
        self.posts.append({"url": url, "content": content, "headers": headers})
        return _FakeResponse(self._status)

    def close(self):
        pass


def _enabled_config(**over):
    base = dict(enabled=True, url="https://splunk:8088/services/collector/event", token="tok", index="main")
    base.update(over)
    return SplunkHecConfig(**base)


def test_disabled_sink_is_noop():
    sink = SplunkHecSink(SplunkHecConfig(enabled=False), start_worker=False)
    assert sink.emit({"kind": "x"}) is False


def test_get_splunk_sink_none_when_env_unset(monkeypatch):
    for key in ("SPLUNK_HEC_ENABLED", "SPLUNK_HEC_URL", "SPLUNK_HEC_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    reset_splunk_sink()
    assert get_splunk_sink() is None
    reset_splunk_sink()


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("SPLUNK_HEC_ENABLED", "true")
    monkeypatch.setenv("SPLUNK_HEC_URL", "https://h:8088/services/collector/event")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "abc")
    monkeypatch.setenv("SPLUNK_HEC_LOG_STATE", "true")
    cfg = SplunkHecConfig.from_env()
    assert cfg.enabled is True
    assert cfg.log_state is True
    # enabled requires url AND token
    monkeypatch.delenv("SPLUNK_HEC_TOKEN")
    assert SplunkHecConfig.from_env().enabled is False


def test_emit_builds_hec_record_shape():
    sink = SplunkHecSink(_enabled_config(), start_worker=False)
    assert sink.emit({"kind": "workflow.step", "node": "executor"}, time_epoch=123.0) is True
    record = sink._queue.get_nowait()
    assert record["time"] == 123.0
    assert record["source"] == "agent-workflow"
    assert record["sourcetype"] == "agent_workflow:step"
    assert record["index"] == "main"
    assert record["event"]["node"] == "executor"


def test_emit_drops_when_queue_full_without_blocking():
    sink = SplunkHecSink(_enabled_config(queue_maxsize=2), start_worker=False)
    assert sink.emit({"n": 1}) is True
    assert sink.emit({"n": 2}) is True
    assert sink.emit({"n": 3}) is False  # dropped, not blocked
    assert sink.dropped == 1


def test_flush_now_posts_batched_events_to_hec():
    client = _FakeClient()
    sink = SplunkHecSink(_enabled_config(), client=client, start_worker=False)
    sink.emit({"n": 1})
    sink.emit({"n": 2})
    sink.flush_now()

    assert len(client.posts) == 1
    post = client.posts[0]
    assert post["headers"]["Authorization"] == "Splunk tok"
    lines = [line for line in post["content"].split("\n") if line]
    assert len(lines) == 2
    assert json.loads(lines[0])["event"]["n"] == 1
    assert sink.sent == 2


def test_send_gives_up_on_permanent_error_without_raising():
    client = _FakeClient(status_code=403)  # permanent
    sink = SplunkHecSink(_enabled_config(), client=client, start_worker=False)
    sink.emit({"n": 1})
    sink.flush_now()  # must not raise
    assert len(client.posts) == 1  # no retry on permanent
    assert sink.sent == 0


def test_build_step_record_is_compact_by_default():
    state = {
        "phase": "executing",
        "artifacts": [{}, {}],
        "tool_calls": [{}],
        "facts": [{}, {}, {}],
        "iteration": {"executor_turns": 2, "explore_cycles": 1, "no_progress_turns": 0},
        "runtime_context": {"secret": "xyz"},
    }
    update = {"events": [{"step": "executor.call_tool"}, {"step": "executor.action"}]}
    rec = build_step_record(thread_id="t1", session_id="s1", node="executor", update=update, state=state, log_state=False, max_event_chars=200000)
    assert rec["kind"] == "workflow.step"
    assert rec["node"] == "executor"
    assert rec["artifact_count"] == 2 and rec["fact_count"] == 3
    assert rec["steps"] == ["executor.call_tool", "executor.action"]
    assert "state" not in rec  # compact by default


def test_build_step_record_includes_state_when_enabled():
    state = {"phase": "done", "artifacts": [{"id": "a1"}], "iteration": {}}
    rec = build_step_record(thread_id="t", session_id="s", node="finalizer", update={}, state=state, log_state=True, max_event_chars=200000)
    assert rec["state"]["phase"] == "done"


def test_build_step_record_truncates_oversized_state():
    state = {"phase": "x", "artifacts": [{"blob": "y" * 5000}], "iteration": {}}
    rec = build_step_record(thread_id="t", session_id="s", node="executor", update={}, state=state, log_state=True, max_event_chars=1000)
    assert rec.get("state_truncated") is True
    assert "state" not in rec


def test_engine_emits_per_step_and_boundary_logs(monkeypatch):
    from pathlib import Path

    from app.agent_workflow import engine as engine_mod
    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.engine import AgentEngine
    from app.agent_workflow.streaming import HostCallbacks, RunRequest
    from app.agent_workflow.tests.test_graph_smoke import MockTools, RoleAwareLlm

    steps: list[str] = []
    events: list[str] = []
    monkeypatch.setattr(engine_mod, "log_workflow_step", lambda **kw: steps.append(kw["node"]))
    monkeypatch.setattr(engine_mod, "log_workflow_event", lambda **kw: events.append(kw["kind"]))

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    engine = AgentEngine(config=config, llm=RoleAwareLlm(), tools=MockTools(), callbacks=HostCallbacks())
    engine.run(RunRequest(query="Find SLA mentions"))

    assert "run.started" in events
    assert "run.completed" in events
    # per-node step logs fired for the graph nodes it went through
    assert "executor" in steps
    assert "finalizer" in steps
