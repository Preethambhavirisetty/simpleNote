"""Evaluate intent detection accuracy against test.examples.json.

Usage:
    cd notelite_agent
    python -m services.intent_service.test
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict

from core.settings import init_llama_index_settings
from services.intent_service.intent import QueryPlanner

_TEST_PATH = os.path.join(os.path.dirname(__file__), "test.examples.json")

# ANSI colors
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _load_cases(path: str | None = None) -> list[dict]:
    with open(path or _TEST_PATH, "r") as f:
        return json.load(f)


def run_evaluation(cases: list[dict]) -> dict:
    planner = QueryPlanner()
    results: list[dict] = []

    for tc in cases:
        query = tc["query"]
        expected = tc["expected_intent"]

        t0 = time.perf_counter()
        plan = planner.plan(query)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        passed = plan.intent == expected
        results.append({
            "id": tc.get("id", "?"),
            "query": query,
            "expected": expected,
            "predicted": plan.intent,
            "confidence": plan.confidence,
            "source": plan.source,
            "difficulty": tc.get("difficulty", ""),
            "passed": passed,
            "time_ms": elapsed_ms,
        })

    return _summarize(results)


def _summarize(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    times = [r["time_ms"] for r in results]
    avg_ms = sum(times) / total if total else 0

    # Per-difficulty breakdown
    by_difficulty: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        d = r["difficulty"] or "unknown"
        by_difficulty[d]["total"] += 1
        if r["passed"]:
            by_difficulty[d]["passed"] += 1

    # Per-intent breakdown
    by_intent: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        by_intent[r["expected"]]["total"] += 1
        if r["passed"]:
            by_intent[r["expected"]]["passed"] += 1

    # ── Print report ─────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"{_BOLD}INTENT DETECTION EVALUATION{_RESET}")
    print(f"{'=' * 70}\n")

    # Individual results
    for r in results:
        status = f"{_GREEN}PASS{_RESET}" if r["passed"] else f"{_RED}FAIL{_RESET}"
        print(
            f"  {status}  {_DIM}[{r['time_ms']:6.1f}ms]{_RESET}  "
            f"{r['query'][:55]:<55}  "
            f"{_DIM}{r['source']:>8}{_RESET}  "
            f"{r['confidence']:.2f}"
        )
        if not r["passed"]:
            print(
                f"        {_RED}expected: {r['expected']}  "
                f"got: {r['predicted']}{_RESET}"
            )

    # Overall
    pct = (passed / total * 100) if total else 0
    color = _GREEN if pct >= 90 else _YELLOW if pct >= 70 else _RED
    print(f"\n{'─' * 70}")
    print(
        f"  {_BOLD}Overall:{_RESET}  "
        f"{color}{passed}/{total} ({pct:.1f}%){_RESET}    "
        f"{_DIM}avg: {avg_ms:.1f}ms  "
        f"min: {min(times):.1f}ms  "
        f"max: {max(times):.1f}ms  "
        f"total: {sum(times) / 1000:.2f}s{_RESET}"
    )

    # By difficulty
    print(f"\n  {_BOLD}By difficulty:{_RESET}")
    for diff in ("straightforward", "casual", "edge_case", "adversarial"):
        if diff not in by_difficulty:
            continue
        d = by_difficulty[diff]
        dp = d["passed"] / d["total"] * 100 if d["total"] else 0
        dc = _GREEN if dp >= 90 else _YELLOW if dp >= 70 else _RED
        print(f"    {diff:<20} {dc}{d['passed']:>2}/{d['total']:<2} ({dp:.0f}%){_RESET}")

    # By intent
    print(f"\n  {_BOLD}By intent:{_RESET}")
    for intent in sorted(by_intent):
        d = by_intent[intent]
        dp = d["passed"] / d["total"] * 100 if d["total"] else 0
        dc = _GREEN if dp >= 90 else _YELLOW if dp >= 70 else _RED
        print(f"    {intent:<22} {dc}{d['passed']:>2}/{d['total']:<2} ({dp:.0f}%){_RESET}")

    # Misclassifications summary
    errors = [r for r in results if not r["passed"]]
    if errors:
        print(f"\n  {_BOLD}Misclassifications ({len(errors)}):{_RESET}")
        for r in errors:
            print(
                f"    {_RED}#{r['id']}{_RESET} \"{r['query'][:60]}\""
            )
            print(
                f"         expected {_CYAN}{r['expected']}{_RESET} "
                f"-> got {_RED}{r['predicted']}{_RESET} "
                f"({r['source']}, conf={r['confidence']:.2f})"
            )

    print(f"\n{'=' * 70}\n")

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "accuracy_pct": round(pct, 1),
        "avg_ms": round(avg_ms, 1),
        "by_difficulty": dict(by_difficulty),
        "by_intent": dict(by_intent),
        "errors": errors,
    }


if __name__ == "__main__":
    init_llama_index_settings()
    cases = _load_cases()
    run_evaluation(cases)
