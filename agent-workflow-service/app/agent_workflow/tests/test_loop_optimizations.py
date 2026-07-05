"""Loop-cost optimizations: native tool calling, conditional finalizer render,
risk-gated reviewer, and config-declared shared resources."""
from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException

from app.agent_workflow.config import parse_agent_config
from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.nodes.finalizer import finalizer_node
from app.agent_workflow.providers.openai_chat import OpenAiChatCompletionsProvider
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider
from app.agent_workflow.streaming import HostCallbacks, RunRequest


def _config(**overrides):
    # Note: planner/reviewer enablement must use the nested objects — the
    # nested pydantic defaults (enabled=True) take precedence over the flat
    # enable_planner/enable_reviewer flags.
    raw = {
        "name": "opt-test",
        "prompts_inline": {"planner": "plan", "executor": "execute", "reviewer": "review"},
        "llm": {"base_url": "http://llm.local/v1", "model": "m"},
        "policy": {
            "enable_fast_path": False,
            "planner": {"enabled": False},
            "reviewer": {"enabled": False},
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(raw.get(key), dict):
            raw[key] = {**raw[key], **value}
        else:
            raw[key] = value
    return raw


class RecordingTools(ToolProvider):
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.searches: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        self.searches.append(query)
        return [
            ToolCandidate(
                name="search_documents",
                title="Search Documents",
                description="Search docs",
                score=0.9,
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            )
        ]

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        if self.fail:
            raise RuntimeError("tool exploded")
        return {"ok": True, "doc_id": "doc-1", "items": [{"text": "SLA", "chunk_id": "c1"}]}


class NativeLlm:
    """Speaks the native tools contract; plain complete() must go unused for
    action selection when native mode is active."""

    def __init__(self):
        self.tool_turns = 0
        self.complete_calls = 0
        self.stream_calls = 0

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        self.complete_calls += 1
        return '{"action":"finish_step"}'

    def stream(self, messages, *, max_tokens: int = 1024):
        self.stream_calls += 1
        yield "Rendered answer."

    def complete_with_tools(self, messages, *, tools, max_tokens: int = 1024) -> dict:
        self.tool_turns += 1
        assert tools and tools[0]["type"] == "function"
        if self.tool_turns == 1:
            return {"content": "", "tool_calls": [{"name": "search_documents", "arguments": {"query": "sla"}}]}
        return {"content": '{"action":"finish_step"}', "tool_calls": []}


def test_native_mode_executes_tool_without_search_roundtrip():
    config = parse_agent_config(_config(llm={"base_url": "http://llm.local/v1", "model": "m", "native_tool_calling": True}))
    llm = NativeLlm()
    tools = RecordingTools()
    engine = AgentEngine(config=config, llm=llm, tools=tools, callbacks=HostCallbacks())

    result = engine.run(RunRequest(query="Find SLA mentions"))

    # Candidates were prefetched deterministically; the model never spent a
    # roundtrip on a search_tools action and never used the JSON-text path.
    assert tools.searches, "prefetch should hit the tool provider"
    assert tools.calls == [("search_documents", {"query": "sla"})]
    assert llm.complete_calls == 0
    assert any(e.get("step") == "executor.search_tools" and e.get("native_prefetch") for e in result.events)
    assert result.answer  # finalizer rendered the mechanical draft
    assert result.error is None


def test_native_mode_falls_back_to_json_path_when_tools_unsupported():
    class BrokenNative(NativeLlm):
        def complete_with_tools(self, messages, *, tools, max_tokens: int = 1024) -> dict:
            raise RuntimeError("tools param rejected")

    config = parse_agent_config(_config(llm={"base_url": "http://llm.local/v1", "model": "m", "native_tool_calling": True}))
    llm = BrokenNative()
    engine = AgentEngine(config=config, llm=llm, tools=RecordingTools(), callbacks=HostCallbacks())

    result = engine.run(RunRequest(query="Find SLA mentions"))

    assert llm.complete_calls >= 1  # JSON path took over
    assert any(e.get("step") == "executor.native_fallback" for e in result.events)
    assert result.error is None


def test_provider_complete_with_tools_parses_tool_calls():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {"function": {"name": "search_documents", "arguments": '{"query": "sla"}'}},
                                {"function": {"name": "bad_json", "arguments": "{not json"}},
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    provider = OpenAiChatCompletionsProvider(base_url="http://llm.local/v1", model="m")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    result = provider.complete_with_tools(
        [{"role": "user", "content": "q"}],
        tools=[{"type": "function", "function": {"name": "search_documents", "parameters": {"type": "object"}}}],
    )
    assert result["tool_calls"][0] == {"name": "search_documents", "arguments": {"query": "sla"}}
    assert result["tool_calls"][1] == {"name": "bad_json", "arguments": {}}
    assert provider.usage_totals()["total_tokens"] == 5


class ExplodingLlm:
    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        raise AssertionError("finalizer must not re-render an LLM prose draft")

    def stream(self, messages, *, max_tokens: int = 1024):
        raise AssertionError("finalizer must not re-render an LLM prose draft")


def test_finalizer_skips_render_for_llm_prose_draft():
    config = parse_agent_config(_config())
    out = finalizer_node(
        {"phase": "done", "draft_answer": "The SLA is 99.9%.", "draft_kind": "llm", "artifacts": []},
        config=config,
        llm=ExplodingLlm(),
    )
    assert out["final_answer"] == "The SLA is 99.9%."


def test_finalizer_renders_mechanical_draft():
    class RenderLlm:
        def complete(self, messages, *, max_tokens: int = 1024) -> str:
            return "Polished answer."

        def stream(self, messages, *, max_tokens: int = 1024):
            yield "Polished answer."

    config = parse_agent_config(_config())
    out = finalizer_node(
        {
            "phase": "done",
            "draft_answer": "Here is what I found from tool results:\n- search_documents: SLA",
            "draft_kind": "mechanical",
            "artifacts": [],
        },
        config=config,
        llm=RenderLlm(),
    )
    assert out["final_answer"] == "Polished answer."


class ScriptedLlm:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = 0

    def complete(self, messages, *, max_tokens: int = 1024) -> str:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response

    def stream(self, messages, *, max_tokens: int = 1024):
        yield self.complete(messages, max_tokens=max_tokens)


def test_on_risk_reviewer_skips_clean_run():
    config = parse_agent_config(
        _config(policy={"enable_fast_path": False, "planner": {"enabled": False}, "reviewer": {"enabled": True, "mode": "on_risk"}})
    )
    llm = ScriptedLlm(['{"action":"draft_answer","answer":"All done."}'])
    engine = AgentEngine(config=config, llm=llm, tools=RecordingTools(), callbacks=HostCallbacks())

    result = engine.run(RunRequest(query="Say hi politely please"))

    assert result.answer == "All done."
    assert result.review.get("reason") == "reviewer_not_required"
    # 1 executor turn; no reviewer call, no finalizer render (prose draft).
    assert llm.calls == 1


def test_on_risk_reviewer_engages_after_tool_failure():
    config = parse_agent_config(
        _config(policy={"enable_fast_path": False, "planner": {"enabled": False}, "reviewer": {"enabled": True, "mode": "on_risk"}})
    )
    llm = ScriptedLlm(
        [
            '{"action":"call_tool","name":"search_documents","arguments":{"query":"sla"}}',
            '{"action":"draft_answer","answer":"Could not search."}',
            "### Verdict\nAPPROVE\n### Issues found\nNone\n### Missing evidence\nNone\n"
            "### Required changes\nNone\n### Approved answer\nThe search failed; please retry.",
        ]
    )
    tools = RecordingTools(fail=True)
    engine = AgentEngine(config=config, llm=llm, tools=tools, callbacks=HostCallbacks())

    result = engine.run(RunRequest(query="Find SLA mentions"))

    assert tools.calls, "tool should have been attempted"
    assert result.review.get("verdict") == "APPROVE"  # reviewer ran because of the failed call


def test_resources_checkpointer_shared_and_resumable_across_engines():
    raw = _config(
        policy={
            "enable_fast_path": False,
            "planner": {"enabled": False},
            "reviewer": {"enabled": False},
            "destructive_tools": ["delete_document"],
        },
        resources={"checkpointer": {"mode": "memory"}},
    )
    delete_call = '{"action":"call_tool","name":"delete_document","arguments":{"doc_id":"d1"}}'
    finish = '{"action":"finish_step"}'

    class DeleteTools(RecordingTools):
        def search_tools(self, query: str, *, limit: int = 25):
            self.searches.append(query)
            return [
                ToolCandidate(
                    name="delete_document",
                    title="Delete Document",
                    description="Delete a doc",
                    score=0.9,
                    input_schema={"type": "object", "properties": {"doc_id": {"type": "string"}}, "required": ["doc_id"]},
                )
            ]

    tools_a, tools_b = DeleteTools(), DeleteTools()
    engine_a = AgentEngine.from_dict(raw, llm=ScriptedLlm([delete_call]), tools=tools_a, callbacks=HostCallbacks())
    engine_b = AgentEngine.from_dict(raw, llm=ScriptedLlm([finish]), tools=tools_b, callbacks=HostCallbacks())

    assert engine_a.checkpointer is engine_b.checkpointer  # one resource, one saver

    paused = engine_a.run(RunRequest(query="Delete doc d1"))
    assert paused.pending_approval is not None
    assert tools_a.calls == []  # fail closed

    # Any engine sharing the resource can resume the thread ("other worker").
    result = engine_b.resume(paused.thread_id, approved=True)
    assert tools_b.calls == [("delete_document", {"doc_id": "d1"})]
    assert result.pending_approval is None


def test_resources_urls_are_host_validated_at_api_boundary():
    from app.api.runtime import _validate_outbound_hosts

    with pytest.raises(HTTPException):
        _validate_outbound_hosts({"resources": {"checkpointer": {"url": "redis://evil.example:6379/0"}}})
    with pytest.raises(HTTPException):
        _validate_outbound_hosts({"resources": {"tool_index": {"search_url": "http://evil.example/search"}}})
    _validate_outbound_hosts({"resources": {"checkpointer": {"url": "redis://127.0.0.1:6379/0"}}})
