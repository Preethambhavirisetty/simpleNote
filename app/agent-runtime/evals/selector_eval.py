"""Measure the router: playbook accuracy, plan accuracy, cost, latency.

Answers one question: is deciding the playbook and the plan in a single LLM
call good enough, or should the plan get its own focused call? Plan accuracy is
reported per playbook, because the split only pays off where a playbook has
many plans to choose between.

Run with agent-domain reachable:

    cd app/agent-domain && .venv/bin/uvicorn api.main:app --port 8100 &
    cd ../agent-runtime && set -a && . ./.env && set +a && \
        DOMAIN_API_BASE=http://127.0.0.1:8100 \
        .venv/bin/python -m evals.selector_eval

    # one mode only, or a quick subset:
    .venv/bin/python -m evals.selector_eval --modes single --limit 10
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.cases import CASES, Case  # noqa: E402
from integrations.domain import load_catalog  # noqa: E402
from loaders.playbook_loader import PlaybookLoader  # noqa: E402
from routing.playbook_selector import PlaybookSelector  # noqa: E402
from schemas.playbook import PlaybookSelection  # noqa: E402


class Result:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.playbook_hits = 0
        self.plan_hits = 0
        self.fallbacks = 0
        self.calls = 0
        self.latencies: list[float] = []
        self.misses: list[tuple[Case, PlaybookSelection, str]] = []
        # playbook -> [plans correct, plans attempted] for cases whose playbook
        # was right, so plan accuracy is not punished twice for a routing miss.
        self.per_playbook: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    def record(self, case: Case, selection: PlaybookSelection, elapsed: float) -> None:
        self.latencies.append(elapsed)
        self.calls += selection.llm_calls
        if selection.selection_mode == "fallback":
            self.fallbacks += 1

        playbook_ok = selection.playbook_id == case.playbook
        plan_ok = playbook_ok and selection.plan_name in case.plans
        self.playbook_hits += playbook_ok
        self.plan_hits += plan_ok

        if playbook_ok:
            counts = self.per_playbook[case.playbook]
            counts[0] += plan_ok
            counts[1] += 1
        if not playbook_ok:
            self.misses.append((case, selection, "playbook"))
        elif not plan_ok:
            self.misses.append((case, selection, "plan"))

    def summary(self, total: int) -> str:
        self.latencies.sort()
        median = self.latencies[len(self.latencies) // 2]
        p90 = self.latencies[min(int(len(self.latencies) * 0.9), len(self.latencies) - 1)]
        return (
            f"{self.mode:8} "
            f"playbook {self.playbook_hits / total:>5.0%}  "
            f"plan {self.plan_hits / total:>5.0%}  "
            f"fallbacks {self.fallbacks:>2}  "
            f"calls/q {self.calls / total:>4.2f}  "
            f"median {median:>5.2f}s  p90 {p90:>5.2f}s"
        )


def run(mode: str, cases: list[Case], selector: PlaybookSelector) -> Result:
    result = Result(mode)
    for index, case in enumerate(cases, start=1):
        started = time.perf_counter()
        selection = selector.select(case.question)
        result.record(case, selection, time.perf_counter() - started)
        if sys.stdout.isatty():  # a progress line only helps an interactive run
            print(f"\r  {mode}: {index}/{len(cases)}", end="", flush=True)
    if sys.stdout.isatty():
        print("\r" + " " * 40, end="\r")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modes", nargs="+", default=["single", "split"])
    parser.add_argument("--limit", type=int, default=0, help="first N cases only")
    args = parser.parse_args()

    cases = CASES[: args.limit] if args.limit else CASES
    playbooks = PlaybookLoader(load_catalog())
    total = len(cases)

    print(f"{total} cases, modes: {', '.join(args.modes)}\n")

    results = []
    for mode in args.modes:
        results.append(run(mode, cases, PlaybookSelector(playbooks, mode=mode)))

    print("── results ─────────────────────────────────────────────────────")
    for result in results:
        print("  " + result.summary(total))

    print("\n── plan accuracy per playbook (only where the playbook was right) ──")
    names = sorted({name for result in results for name in result.per_playbook})
    header = "  " + f"{'playbook':16}" + "".join(f"{r.mode:>12}" for r in results)
    print(header)
    for name in names:
        plans = len(playbooks.get_playbook(name).plans)
        row = f"  {name + f' ({plans})':16}"
        for result in results:
            hits, attempts = result.per_playbook.get(name, [0, 0])
            row += f"{(f'{hits}/{attempts}'):>12}"
        print(row)

    for result in results:
        if not result.misses:
            continue
        print(f"\n── {result.mode} misses ──")
        for case, selection, kind in result.misses:
            print(f"  [{kind}] {case.question}")
            print(
                f"    want {case.playbook}/{'|'.join(case.plans)}, "
                f"got {selection.playbook_id}/{selection.plan_name}"
            )
            print(f"    reason: {selection.reason[:140]}")


if __name__ == "__main__":
    main()
