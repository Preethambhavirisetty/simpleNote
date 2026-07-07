from __future__ import annotations

import time

from app.agent_workflow.config import parse_agent_config
from app.agent_workflow.context.builder import ContextBuilder
from app.agent_workflow.graph import _should_compact
from app.agent_workflow.nodes.fact_extractor import fact_extractor_node
from app.agent_workflow.nodes.summarizer import summarizer_node


def _cfg(**summary):
    policy = {"enable_running_summary": True}
    if summary:
        policy["summary"] = summary
    return parse_agent_config(
        {
            "name": "sum",
            "prompts_inline": {"planner": "p", "executor": "e", "reviewer": "r"},
            "llm": {"base_url": "http://llm.local/v1", "model": "m"},
            "policy": policy,
        }
    )


class _MemoLlm:
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        return "Confirmed facts:\n- panel count = 16"

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


class _SlowLlm:
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        time.sleep(0.05)
        return "too late"

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def _artifacts(n):
    return [
        {"id": f"a{i}", "tool": "t", "summary": f"finding {i}", "composite_score": i * 0.1}
        for i in range(n)
    ]


def test_summarizer_folds_low_score_artifacts_and_keeps_top():
    config = _cfg(compact_after_artifacts=4, keep_after_summary=2, max_cycles=3)
    out = summarizer_node({"artifacts": _artifacts(6), "iteration": {}}, config=config, llm=_MemoLlm())

    assert out["phase"] == "executing"
    assert out["iteration"]["summaries"] == 1
    assert out["running_summary"].startswith("Confirmed facts")
    # Keeps the two highest-scoring artifacts verbatim, folds the rest.
    assert {a["id"] for a in out["artifacts"]} == {"a5", "a4"}
    assert out["events"][0]["step"] == "summarizer.completed"
    assert out["events"][0]["folded_count"] == 4


def test_summarizer_timeout_falls_back_to_deterministic_memo():
    config = _cfg(compact_after_artifacts=2, keep_after_summary=0)
    config.policy.llm_timeout_seconds = 0.01
    out = summarizer_node({"artifacts": _artifacts(3), "iteration": {}}, config=config, llm=_SlowLlm())

    assert out["phase"] == "executing"
    assert out["running_summary"]  # deterministic memo, not empty
    assert out["events"][0]["step"] == "summarizer.timeout"
    assert out["artifacts"] == []  # keep_after_summary=0 folds everything


def test_should_compact_gated_by_flag_cap_and_threshold():
    on = _cfg(compact_after_artifacts=3, max_cycles=2)
    off = parse_agent_config(
        {
            "name": "x",
            "prompts_inline": {"planner": "p", "executor": "e", "reviewer": "r"},
            "llm": {"base_url": "http://llm.local/v1", "model": "m"},
            "policy": {},  # enable_running_summary defaults False
        }
    )
    state = {"phase": "executing", "iteration": {"summaries": 0}, "artifacts": _artifacts(3)}

    assert _should_compact(state, on) is True
    assert _should_compact(state, off) is False  # disabled by default
    assert _should_compact({**state, "artifacts": _artifacts(2)}, on) is False  # under threshold
    assert _should_compact({**state, "iteration": {"summaries": 2}}, on) is False  # cap reached


def test_fact_extractor_seeds_running_summary_facts():
    config = _cfg()
    out = fact_extractor_node(
        {"artifacts": [], "running_summary": "Confirmed facts:\n- panel count = 16\n- region = us-east"},
        config=config,
    )
    texts = [fact["text"] for fact in out["facts"]]
    assert "panel count = 16" in texts
    assert "region = us-east" in texts
    assert "Confirmed facts:" not in texts  # header line skipped
    assert any(fact["tool"] == "running_summary" for fact in out["facts"])


def test_builder_injects_running_summary_for_executor_only():
    config = _cfg()
    state = {"user_query": "q", "running_summary": "Confirmed facts:\n- x=1"}

    executor_msg = ContextBuilder(config).build(state, "executor")[1]["content"]
    planner_msg = ContextBuilder(config).build(state, "planner")[1]["content"]

    assert "Working memory" in executor_msg
    assert "Working memory" not in planner_msg


def test_graph_detours_through_summarizer_and_still_completes():
    # End-to-end: with a low compaction threshold the executor loop must detour
    # through the summarizer, populate running memory, and still finish.
    from pathlib import Path

    from app.agent_workflow.config import load_agent_config
    from app.agent_workflow.engine import AgentEngine
    from app.agent_workflow.streaming import HostCallbacks, RunRequest
    from app.agent_workflow.tests.test_graph_smoke import MockTools, RoleAwareLlm

    config = load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")
    config.policy.enable_running_summary = True
    config.policy.summary.compact_after_artifacts = 1
    config.policy.summary.keep_after_summary = 0

    llm = RoleAwareLlm()
    engine = AgentEngine(config=config, llm=llm, tools=MockTools(), callbacks=HostCallbacks())
    result = engine.run(RunRequest(query="Find SLA mentions"))

    assert "summarizer" in llm.roles  # the detour actually fired
    assert "SLA" in result.answer  # and the run still produced an answer
    assert result.error is None
