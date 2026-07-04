from __future__ import annotations

import json
import time
from typing import Any, Callable

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.context import (
    ContextBuilder,
    extract_source_ref,
    make_artifact_id,
    score_artifact,
    truncate_tool_result,
)
from app.agent_workflow.parsing import parse_executor_action
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.state import AgentState, Artifact, ToolCallRecord


def _called_tools_for_step(state: AgentState, step_index: int) -> set[str]:
    return {
        str(artifact.get("tool") or "")
        for artifact in (state.get("artifacts") or [])
        if int(artifact.get("step_index", -1)) == step_index and artifact.get("tool")
    }


def _pick_coerced_tool(
    candidates: list[dict[str, Any]],
    *,
    current_step: dict[str, Any],
    user_query: str,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    exclude = exclude or set()
    available = [c for c in candidates if c.get("name") not in exclude]
    pool = available or list(candidates)
    hints = " ".join(
        part
        for part in [
            current_step.get("tool_hint", ""),
            current_step.get("title", ""),
            current_step.get("action", ""),
            user_query,
        ]
        if part
    ).lower()

    def score(tool: dict[str, Any]) -> float:
        name = str(tool.get("name") or "").lower()
        desc = str(tool.get("description") or tool.get("title") or "").lower()
        base = float(tool.get("score") or 0.0)
        bonus = 0.0
        tool_hint = str(current_step.get("tool_hint") or "").lower()
        if tool_hint and tool_hint.replace(" ", "_") in name:
            bonus += 1.0
        for token in hints.replace("_", " ").split():
            if len(token) < 4:
                continue
            if token in name:
                bonus += 0.35
            elif token in desc:
                bonus += 0.1
        if "panel" in hints and "panel" in name:
            bonus += 0.8
        if "panel" in hints and "dashboard" in name and "panel" not in name:
            bonus -= 0.5
        if name in exclude:
            bonus -= 2.0
        return base + bonus

    return max(pool, key=score)


def _default_tool_arguments(tool_name: str, *, state: AgentState, current_step: dict[str, Any]) -> dict[str, Any]:
    query = str(state.get("user_query") or current_step.get("action") or "").strip()
    runtime = state.get("runtime_context") or {}
    user_id = str(runtime.get("user_id") or runtime.get("tenant_id") or "").strip()
    role = str(runtime.get("role") or "user")
    access_token = str(runtime.get("access_token") or "").strip()

    if tool_name == "search_panels":
        return {"query": query or "panels", "top_k": 25}
    if tool_name == "search_documents":
        return {"query": query}
    if tool_name in {"search_notes", "locate_notes"}:
        args: dict[str, Any] = {"query": query, "user_id": user_id, "role": role}
        history = state.get("messages") or []
        if history:
            args["history"] = history[-6:]
        return args
    if tool_name == "summarize_notes":
        return {"query": query, "user_id": user_id}
    if tool_name in {"list_folders", "list_notes"}:
        return {"access_token": access_token}
    return {}


def _default_arguments_ready(tool_name: str, arguments: dict[str, Any]) -> bool:
    if tool_name in {"search_notes", "locate_notes"}:
        return bool(arguments.get("query") and arguments.get("user_id"))
    if tool_name == "summarize_notes":
        return bool(arguments.get("user_id") and (arguments.get("query") or arguments.get("note_ids")))
    if tool_name in {"list_folders", "list_notes"}:
        return bool(arguments.get("access_token"))
    return True


def _synthesize_draft_answer(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> str:
    builder = ContextBuilder(config)
    messages = builder.build(state, "executor")
    messages[-1]["content"] += (
        "\n\nAll plan steps are complete. Write the final user-facing answer using the artifacts above.\n"
        'Return ONLY JSON: {"action":"draft_answer","answer":"..."}'
    )
    raw = llm.complete(messages, max_tokens=2000)
    action = parse_executor_action(raw)
    answer = str(action.get("answer") or raw).strip()
    return answer or _fallback_answer(state)


def _execute_tool_call_action(
    *,
    state: AgentState,
    config: AgentConfig,
    tools: ToolProvider,
    action: dict[str, Any],
    updates: dict[str, Any],
    iteration: dict[str, Any],
    step_index: int,
    step_query: str,
    on_tool_call: Callable[[str, dict[str, Any], Any], None] | None,
    on_artifact: Callable[[Artifact], None] | None,
    on_destructive_action: Callable[[str, dict[str, Any]], bool] | None,
) -> dict[str, Any]:
    tool_name = str(action.get("name") or "")
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    if not tool_name:
        updates["error"] = "call_tool missing name"
        return updates

    if tool_name in config.policy.destructive_tools:
        approved = True
        if config.policy.require_destructive_confirmation and on_destructive_action:
            approved = on_destructive_action(tool_name, arguments)
        if not approved:
            updates["events"].append({"step": "executor.destructive_blocked", "tool": tool_name})
            return updates

    started = time.perf_counter()
    status = "ok"
    error: str | None = None
    result: Any = None
    try:
        result = tools.call_tool(tool_name, arguments)
        if on_tool_call:
            on_tool_call(tool_name, arguments, result)
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error = str(exc)
        result = {"ok": False, "error": error}

    latency_ms = int((time.perf_counter() - started) * 1000)
    record: ToolCallRecord = {
        "name": tool_name,
        "args_preview": json.dumps(arguments)[:300],
        "status": status,
        "latency_ms": latency_ms,
        "error": error,
    }
    tool_calls = list(state.get("tool_calls") or [])
    tool_calls.append(record)
    iteration["tool_calls"] = int(iteration.get("tool_calls") or 0) + 1
    updates["tool_calls"] = tool_calls
    updates["iteration"] = iteration

    summary, raw_ref, truncated = truncate_tool_result(
        result,
        step_query=step_query,
        policy=config.policy.truncation,
    )
    scores = score_artifact(
        summary=summary,
        step_query=step_query,
        tool_result=result if isinstance(result, dict) else {"result": result},
        existing_artifacts=state.get("artifacts") or [],
        policy=config.policy.truncation,
        created_at=time.time(),
    )
    artifact: Artifact = {
        "id": make_artifact_id(tool_name, summary),
        "tool": tool_name,
        "summary": summary,
        "raw_ref": raw_ref,
        "source_ref": extract_source_ref(result if isinstance(result, dict) else {}),
        "scores": scores,
        "composite_score": scores["composite"],
        "created_at": time.time(),
        "step_index": step_index,
        "truncated": truncated,
    }
    artifacts = list(state.get("artifacts") or [])
    artifacts.append(artifact)
    updates["artifacts"] = artifacts
    if on_artifact:
        on_artifact(artifact)
    updates["events"].append(
        {
            "step": "executor.call_tool",
            "tool": tool_name,
            "status": status,
            "arguments": arguments,
            "error": error,
        }
    )
    return updates


def executor_node(
    state: AgentState,
    *,
    config: AgentConfig,
    llm: LlmProvider,
    tools: ToolProvider,
    on_tool_search: Callable[[str, list[dict[str, Any]]], None] | None = None,
    on_tool_call: Callable[[str, dict[str, Any], Any], None] | None = None,
    on_artifact: Callable[[Artifact], None] | None = None,
    on_destructive_action: Callable[[str, dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    iteration = dict(state.get("iteration") or {})
    iteration["executor_turns"] = int(iteration.get("executor_turns") or 0) + 1
    if iteration["executor_turns"] > config.policy.max_executor_iterations:
        draft = state.get("draft_answer") or _synthesize_draft_answer(state, config=config, llm=llm)
        return {
            "phase": "reviewing",
            "draft_answer": draft,
            "iteration": iteration,
            "events": [{"step": "executor.iteration_limit", "synthesized": True}],
        }

    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
    step_index = int(state.get("current_step_index") or 0)
    if step_index >= len(steps) and not state.get("draft_answer"):
        draft = _synthesize_draft_answer(state, config=config, llm=llm)
        return {
            "phase": "reviewing",
            "draft_answer": draft,
            "iteration": iteration,
            "events": [{"step": "executor.draft_answer", "synthesized": True}],
        }

    current_step = steps[step_index] if step_index < len(steps) else {}
    step_query = " ".join(
        part for part in [current_step.get("title", ""), current_step.get("action", ""), state.get("user_query", "")] if part
    )

    builder = ContextBuilder(config)
    messages = builder.build(state, "executor")
    messages[-1]["content"] += (
        "\n\nReturn ONLY JSON with one action:\n"
        '{"action":"search_tools","query":"..."}\n'
        '{"action":"call_tool","name":"tool_name","arguments":{...}}\n'
        '{"action":"finish_step"}\n'
        '{"action":"draft_answer","answer":"..."}'
    )

    raw = llm.complete(messages, max_tokens=1200)
    action = parse_executor_action(raw)
    action_type = str(action.get("action") or "").lower()

    candidate_tools = list(state.get("candidate_tools") or [])
    called_this_step = _called_tools_for_step(state, step_index)
    step_has_results = bool(called_this_step)

    updates: dict[str, Any] = {"iteration": iteration, "phase": "executing"}
    updates["events"] = [
        {
            "step": "executor.action",
            "action": action_type,
            "step_index": step_index,
            "step_title": current_step.get("title", ""),
            "executor_turn": iteration["executor_turns"],
        }
    ]

    # Search already ran for this step — call the best matching tool instead of looping.
    if action_type == "search_tools" and candidate_tools and not step_has_results:
        picked = _pick_coerced_tool(
            candidate_tools,
            current_step=current_step,
            user_query=str(state.get("user_query") or ""),
        )
        tool_name = str(picked.get("name") or "")
        arguments = _default_tool_arguments(tool_name, state=state, current_step=current_step)
        if _default_arguments_ready(tool_name, arguments):
            action_type = "call_tool"
            action = {"action": "call_tool", "name": tool_name, "arguments": arguments}
            updates["events"].append(
                {
                    "step": "executor.coerced",
                    "message": f"Tools already found; calling {picked.get('name')} instead of searching again",
                }
            )
        else:
            updates["events"].append(
                {
                    "step": "executor.coerced",
                    "message": f"Tool {tool_name} needs explicit arguments; asking executor to continue",
                }
            )
            return updates

    # Step has results but LLM searched again — call another unused tool or finish.
    if action_type == "search_tools" and step_has_results:
        unused = [t for t in candidate_tools if t.get("name") not in called_this_step]
        if unused:
            picked = _pick_coerced_tool(
                unused,
                current_step=current_step,
                user_query=str(state.get("user_query") or ""),
            )
            tool_name = str(picked.get("name") or "")
            arguments = _default_tool_arguments(tool_name, state=state, current_step=current_step)
            if _default_arguments_ready(tool_name, arguments):
                action_type = "call_tool"
                action = {"action": "call_tool", "name": tool_name, "arguments": arguments}
                updates["events"].append(
                    {
                        "step": "executor.coerced",
                        "message": f"Step has results; calling {picked.get('name')} for more evidence",
                    }
                )
            else:
                action_type = "finish_step"
                updates["events"].append(
                    {"step": "executor.coerced", "message": f"Skipping {tool_name}; required default arguments are missing"}
                )
        else:
            action_type = "finish_step"
            updates["events"].append(
                {"step": "executor.coerced", "message": "Step already has tool results; finishing step"}
            )

    if action_type == "call_tool":
        tool_name = str(action.get("name") or "")
        step_call_count = len(called_this_step)
        max_per_step = config.policy.max_tool_calls_per_step
        if tool_name in called_this_step or step_call_count >= max_per_step:
            unused = [t for t in candidate_tools if t.get("name") not in called_this_step]
            if unused and step_call_count < max_per_step:
                picked = _pick_coerced_tool(
                    unused,
                    current_step=current_step,
                    user_query=str(state.get("user_query") or ""),
                )
                tool_name = str(picked.get("name") or "")
                arguments = _default_tool_arguments(tool_name, state=state, current_step=current_step)
                if _default_arguments_ready(tool_name, arguments):
                    action = {"action": "call_tool", "name": tool_name, "arguments": arguments}
                    updates["events"].append(
                        {
                            "step": "executor.coerced",
                            "message": f"Skipping duplicate tool; calling {tool_name} instead",
                        }
                    )
                else:
                    action_type = "finish_step"
                    updates["events"].append(
                        {"step": "executor.coerced", "message": f"Skipping {tool_name}; required default arguments are missing"}
                    )
            else:
                action_type = "finish_step"
                updates["events"].append(
                    {
                        "step": "executor.coerced",
                        "message": "Enough tool results for this step; finishing step",
                    }
                )

    if action_type == "search_tools":
        query = str(action.get("query") or step_query)
        try:
            candidates = tools.search_tools(query)
        except Exception as exc:  # noqa: BLE001
            return {
                "error": str(exc),
                "phase": "reviewing",
                "draft_answer": f"Tool search failed: {exc}",
                "iteration": iteration,
                "events": updates["events"],
            }

        candidate_dicts = [
            {
                "name": c.name,
                "title": c.title,
                "description": c.description,
                "score": c.score,
                "input_schema": c.input_schema,
            }
            for c in candidates
        ]
        if not candidate_dicts:
            return {
                "error": f"No tools matched: {query}",
                "phase": "reviewing",
                "draft_answer": (
                    f"No tools matched: {query}. "
                    "Ingest the MCP tool catalog into Qdrant (see mcp-service MCP_TOOL_INDEX_COLLECTION)."
                ),
                "iteration": iteration,
                "events": updates["events"],
            }

        if on_tool_search:
            on_tool_search(query, candidate_dicts)
        updates["candidate_tools"] = candidate_dicts
        updates["events"].append(
            {
                "step": "executor.search_tools",
                "query": query,
                "tool_count": len(candidate_dicts),
                "tools": [c["name"] for c in candidate_dicts[:7]],
            }
        )
        picked = _pick_coerced_tool(
            candidate_dicts,
            current_step=current_step,
            user_query=str(state.get("user_query") or ""),
        )
        tool_name = str(picked.get("name") or "")
        updates["events"].append(
            {
                "step": "executor.coerced",
                "message": f"Calling {tool_name} immediately after tool discovery",
            }
        )
        arguments = _default_tool_arguments(tool_name, state=state, current_step=current_step)
        if not _default_arguments_ready(tool_name, arguments):
            updates["events"].append(
                {"step": "executor.coerced", "message": f"Tool {tool_name} needs explicit arguments; asking executor to continue"}
            )
            return updates
        return _execute_tool_call_action(
            state=state,
            config=config,
            tools=tools,
            action={"action": "call_tool", "name": tool_name, "arguments": arguments},
            updates=updates,
            iteration=iteration,
            step_index=step_index,
            step_query=step_query,
            on_tool_call=on_tool_call,
            on_artifact=on_artifact,
            on_destructive_action=on_destructive_action,
        )

    if action_type == "call_tool":
        return _execute_tool_call_action(
            state=state,
            config=config,
            tools=tools,
            action=action,
            updates=updates,
            iteration=iteration,
            step_index=step_index,
            step_query=step_query,
            on_tool_call=on_tool_call,
            on_artifact=on_artifact,
            on_destructive_action=on_destructive_action,
        )

    if action_type == "finish_step":
        next_index = step_index + 1
        updates["current_step_index"] = next_index
        updates["candidate_tools"] = []
        updates["events"].append({"step": "executor.finish_step", "step_index": step_index})
        if next_index >= len(steps):
            updates["phase"] = "executing"
        return updates

    answer = str(action.get("answer") or raw).strip()
    updates["draft_answer"] = answer
    updates["phase"] = "reviewing"
    updates["events"].append({"step": "executor.draft_answer"})
    return updates


def _fallback_answer(state: AgentState) -> str:
    artifacts = state.get("artifacts") or []
    if not artifacts:
        return "I completed the available steps but could not produce a detailed answer."
    lines = ["Here is what I found:"]
    for artifact in artifacts[:5]:
        lines.append(f"- {artifact.get('tool')}: {str(artifact.get('summary', ''))[:400]}")
    return "\n".join(lines)
