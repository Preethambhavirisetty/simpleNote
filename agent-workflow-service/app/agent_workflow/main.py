"""CLI entry point for the LangGraph agent workflow engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_ORCHESTRATOR_ROOT = _PACKAGE_DIR.parent.parent
_DEFAULT_CONFIG = _PACKAGE_DIR / "agents" / "default.yaml"


def _print_review(event: dict) -> None:
    verdict = event.get("verdict", "?")
    print(f"\n[review] verdict={verdict}", flush=True)
    print(
        f"         artifacts={event.get('artifact_count', 0)} "
        f"tool_calls={event.get('tool_call_count', 0)}",
        flush=True,
    )
    preview = (event.get("draft_answer_preview") or "").strip()
    if preview:
        print(f"         draft: {preview[:200]}", flush=True)
    for label, key in (
        ("issues", "issues"),
        ("missing evidence", "missing_evidence"),
        ("required changes", "required_changes"),
    ):
        items = [i for i in (event.get(key) or []) if i and str(i).lower() != "none"]
        if items:
            print(f"         {label}:", flush=True)
            for item in items:
                print(f"           - {item}", flush=True)


def main() -> None:
    if str(_ORCHESTRATOR_ROOT) not in sys.path:
        sys.path.insert(0, str(_ORCHESTRATOR_ROOT))

    from app.agent_workflow.engine import AgentEngine
    from app.agent_workflow.streaming import HostCallbacks, RunRequest

    parser = argparse.ArgumentParser(description="Run the LangGraph agent workflow engine")
    parser.add_argument("--config", default=str(_DEFAULT_CONFIG), help="Path to agent YAML config")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Approve destructive tool calls without prompting (non-interactive runs)",
    )
    parser.add_argument("query", nargs="*", help="User query")
    args = parser.parse_args()

    query = " ".join(args.query).strip()
    if not query:
        print("Query is required.", file=sys.stderr)
        raise SystemExit(2)

    def approve_destructive(tool: str, arguments: dict) -> bool:
        if args.yes:
            return True
        prompt = f"\n[approval] run destructive tool {tool} with {json.dumps(arguments)[:200]}? [y/N] "
        return input(prompt).strip().lower() in {"y", "yes"}

    engine = AgentEngine.from_config(
        args.config,
        callbacks=HostCallbacks(on_destructive_action=approve_destructive),
    )
    print(f"Running agent: {engine.config.name}\n", flush=True)

    for event in engine.stream(RunRequest(query=query, session_id="cli")):
        event_type = event.get("type")
        if event_type == "status":
            print(f"[status] {event.get('message')}", flush=True)
        elif event_type == "plan":
            print(f"[plan] goal: {event.get('goal', '')}", flush=True)
            for idx, title in enumerate(event.get("steps") or [], start=1):
                print(f"       {idx}. {title}", flush=True)
        elif event_type == "debug":
            print(f"[debug] {event.get('message')}", flush=True)
        elif event_type == "agent_activity":
            print(f"[activity] {event.get('label')}", flush=True)
            tool_count = event.get("tool_count")
            tools = event.get("tools") or []
            if tool_count is not None:
                print(f"           matched {tool_count} tool(s)", flush=True)
            if tools:
                print(f"           top: {', '.join(tools)}", flush=True)
            if event.get("arguments"):
                print(f"           args: {json.dumps(event['arguments'])[:200]}", flush=True)
            if event.get("error"):
                print(f"           error: {event['error']}", flush=True)
        elif event_type == "pending_approval":
            # Unreachable with the interactive approver above, but printed for
            # hosts embedding this loop without a synchronous callback.
            print(
                f"[approval] paused: {event.get('tool')} requires approval "
                f"(thread {event.get('thread_id')})",
                flush=True,
            )
        elif event_type == "review":
            _print_review(event)
        elif event_type == "delta":
            print(f"\n[draft]\n{event.get('content', '')}", flush=True)
        elif event_type == "done":
            print("\n--- done ---")
            print(event.get("answer") or "")
            if event.get("error"):
                print(f"error: {event.get('error')}", file=sys.stderr)
                raise SystemExit(1)


if __name__ == "__main__":
    main()
