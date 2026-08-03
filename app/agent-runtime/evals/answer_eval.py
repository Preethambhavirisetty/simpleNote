"""Run the answer-quality cases against a live runtime.

Needs the whole stack up - domain, MCP, inference host - and a corpus matching
`answers.CORPUS`. Routing quality is measured separately by `selector_eval.py`;
this asks whether the answer that came back is true.

    podman exec -e AGENT_KEY=... notelite-agent-runtime \\
        python -m evals.answer_eval --user-id <uuid>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.answers import CASES, CORPUS, evaluate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--base", default="http://127.0.0.1:8200")
    parser.add_argument("--api-key", default=os.getenv("AGENT_KEY", ""))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cases = CASES[: args.limit] if args.limit else CASES
    print(f"{len(cases)} answer cases against the corpus:{CORPUS}")

    passed = 0
    failures: list[tuple[str, list[str], str]] = []

    for case in cases:
        try:
            response = httpx.post(
                f"{args.base}/api/agent-workflow/run",
                headers={"X-API-Key": args.api_key},
                json={
                    "query": case.question,
                    "runtime_context": {"user_id": args.user_id, "role": "user"},
                },
                timeout=240,
            )
            payload = response.json()
        except Exception as exc:  # a dead dependency is a result, not a crash
            failures.append((case.question, [f"request failed: {exc}"], ""))
            continue

        problems = evaluate(payload, case)
        answer = str(payload.get("answer") or "")
        if problems:
            failures.append((case.question, problems, answer))
        else:
            passed += 1
        route = f"{payload.get('playbook')}/{payload.get('plan')}"
        mark = "ok " if not problems else "FAIL"
        print(f"  [{mark}] {case.question[:52]:54} {route}")

    total = len(cases)
    print(f"\n{passed}/{total} answers correct ({passed / total:.0%})")

    for question, problems, answer in failures:
        print(f"\n  FAIL {question}")
        for problem in problems:
            print(f"       - {problem}")
        if answer:
            print(f"       answer: {answer[:160]}")


if __name__ == "__main__":
    main()
