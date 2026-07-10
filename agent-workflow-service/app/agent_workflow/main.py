"""CLI entry point for the LangGraph agent workflow engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_ORCHESTRATOR_ROOT = _PACKAGE_DIR.parent.parent
_DEFAULT_CONFIG = _PACKAGE_DIR / "agents" / "default.yaml"


def main() -> None:
    """Run the command-line workflow entrypoint."""
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
        """Ask the CLI user to approve or deny a destructive tool call."""
        if args.yes:
            return True
        prompt = f"\n[approval] run destructive tool {tool} with {json.dumps(arguments)[:200]}? [y/N] "
        return input(prompt).strip().lower() in {"y", "yes"}

    engine = AgentEngine.from_config(
        args.config,
        callbacks=HostCallbacks(on_destructive_action=approve_destructive),
    )

    # Per-step run visibility is streamed asynchronously to Splunk HEC by the
    # engine; the CLI only surfaces the final answer (and any error) here.
    answer = ""
    error = None
    for event in engine.stream(RunRequest(query=query, session_id="cli")):
        if event.get("type") == "done":
            answer = event.get("answer") or ""
            error = event.get("error")

    print(answer)
    if error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
