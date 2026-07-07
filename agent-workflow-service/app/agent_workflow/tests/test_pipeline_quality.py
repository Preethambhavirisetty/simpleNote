from __future__ import annotations

from pathlib import Path

from app.agent_workflow.config import load_agent_config
from app.agent_workflow.nodes.fact_extractor import fact_extractor_node
from app.agent_workflow.nodes.reviewer import _parse_review
from app.agent_workflow.nodes.synthesizer import synthesizer_node


def _config():
    return load_agent_config(Path(__file__).resolve().parents[1] / "agents" / "document.yaml")


class _StubLlm:
    def __init__(self, text: str = "prose answer"):
        self.text = text
        self.calls = 0

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        self.calls += 1
        return self.text

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.text


# --- Phase 1: structured fact contract -------------------------------------


def test_fact_extractor_prefers_structured_facts_over_line_splitting():
    state = {
        "artifacts": [
            {
                "id": "a1",
                "tool": "get_dashboard",
                "composite_score": 0.9,
                # Summary would line-split into noise; structured facts win.
                "summary": "line one\nline two\nline three",
                "raw_ref": {"facts": ["panel 'CPU' shows 42%", "panel 'Mem' shows 71%"]},
            }
        ]
    }

    result = fact_extractor_node(state, config=_config())
    texts = [fact["text"] for fact in result["facts"]]

    assert "panel 'CPU' shows 42%" in texts
    assert "panel 'Mem' shows 71%" in texts
    # Line-split summary content must not leak in when structured facts exist.
    assert "line one" not in texts


def test_fact_extractor_reads_nested_structured_facts_with_metadata():
    state = {
        "artifacts": [
            {
                "id": "a1",
                "tool": "get_report",
                "composite_score": 0.5,
                "summary": "",
                "raw_ref": {
                    "data": {
                        "facts": [
                            {"text": "total errors = 5", "confidence": 0.95, "source_ref": {"panel": "errors"}},
                        ]
                    }
                },
            }
        ]
    }

    result = fact_extractor_node(state, config=_config())
    fact = result["facts"][0]

    assert fact["text"] == "total errors = 5"
    assert fact["confidence"] == 0.95
    assert fact["source_ref"] == {"panel": "errors"}


def test_fact_extractor_derives_facts_from_generic_collections():
    state = {
        "artifacts": [
            {
                "id": "a1",
                "tool": "list_dashboards",
                "composite_score": 0.7,
                "summary": "",
                "raw_ref": {
                    "panels": [
                        {"title": "CPU", "value": 42, "extra": {"skip": "nested"}},
                        {"title": "Mem", "value": 71},
                    ]
                },
            }
        ]
    }

    result = fact_extractor_node(state, config=_config())
    texts = [fact["text"] for fact in result["facts"]]

    assert any("title=CPU" in text and "value=42" in text for text in texts)
    assert any("title=Mem" in text for text in texts)
    # Nested dict values are skipped to keep facts compact.
    assert all("skip" not in text for text in texts)


def test_fact_extractor_falls_back_to_summary_line_splitting():
    state = {
        "artifacts": [
            {
                "id": "a1",
                "tool": "search_documents",
                "composite_score": 0.4,
                "summary": "- SLA is 99.9%\n- Region is us-east",
                "raw_ref": {"type": "object"},
            }
        ]
    }

    result = fact_extractor_node(state, config=_config())
    texts = [fact["text"] for fact in result["facts"]]

    assert "SLA is 99.9%" in texts
    assert "Region is us-east" in texts


# --- Phase 3: reviewer parsing ---------------------------------------------


def test_parse_review_reads_json_first():
    review, failed = _parse_review('{"verdict":"APPROVE","issues":[],"required_changes":[]}')
    assert failed is False
    assert review["verdict"] == "APPROVE"


def test_parse_review_falls_back_to_markdown():
    text = "### Verdict\nREVISE\n### Issues found\n- unsupported claim\n### Required changes\n1. cite the source"
    review, failed = _parse_review(text)
    assert failed is False
    assert review["verdict"] == "REVISE"
    assert "unsupported claim" in review["issues"]


def test_parse_review_safe_revise_on_unparseable_output():
    review, failed = _parse_review("I think the draft is basically fine, ship it.")
    assert failed is True
    assert review["verdict"] == "REVISE"


def test_parse_review_rejects_non_review_json():
    # An executor-style action payload must not be mistaken for a verdict.
    review, failed = _parse_review('{"action":"draft_answer","answer":"Found SLA."}')
    assert failed is True
    assert review["verdict"] == "REVISE"


# --- Phase 4: synthesizer telemetry ----------------------------------------


def test_synthesizer_emits_skipped_event_for_executor_draft():
    state = {"facts": [], "draft_answer": "executor wrote this", "tool_calls": [], "artifacts": []}
    result = synthesizer_node(state, config=_config(), llm=_StubLlm())
    steps = [event["step"] for event in result["events"]]
    assert steps == ["synthesizer.skipped"]
    assert result["draft_kind"] == "executor_draft"


def test_synthesizer_emits_fallback_event_when_no_facts():
    state = {"facts": [], "draft_answer": "", "tool_calls": [], "artifacts": []}
    result = synthesizer_node(state, config=_config(), llm=_StubLlm())
    steps = [event["step"] for event in result["events"]]
    assert steps == ["synthesizer.fallback"]


def test_synthesizer_emits_completed_event_with_facts():
    state = {
        "facts": [{"text": "SLA is 99.9%", "tool": "search_documents", "id": "f1"}],
        "tool_calls": [],
        "artifacts": [],
        "plan": {"goal": "Find SLA"},
    }
    result = synthesizer_node(state, config=_config(), llm=_StubLlm("The SLA is 99.9%."))
    steps = [event["step"] for event in result["events"]]
    assert steps == ["synthesizer.completed"]
    assert result["draft_kind"] == "llm"
