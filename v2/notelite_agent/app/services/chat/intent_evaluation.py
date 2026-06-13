from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from app.services.chat.intent_classification import IntentResult, classify_intent


@dataclass(frozen=True)
class GoldenIntentCase:
    query: str
    intent: str


@dataclass(frozen=True)
class IntentEvaluationReport:
    total: int
    correct: int
    accuracy: float
    confusion: dict[str, dict[str, int]]
    failures: list[dict[str, str | float]]


def load_golden_set(path: str | Path) -> list[GoldenIntentCase]:
    """Load labelled intent cases from YAML for reproducible evaluation."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Golden intent set must be a YAML list")
    cases = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("query"), str) or not isinstance(item.get("intent"), str):
            raise ValueError("Each golden intent case requires string query and intent fields")
        cases.append(GoldenIntentCase(item["query"].strip(), item["intent"].strip()))
    return cases


def evaluate_intents(
    cases: Sequence[GoldenIntentCase],
    classifier: Callable[[str], IntentResult] = classify_intent,
) -> IntentEvaluationReport:
    """Evaluate a classifier against labelled cases and build a confusion matrix."""
    correct = 0
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    failures = []
    for case in cases:
        result = classifier(case.query)
        confusion[case.intent][result.intent] += 1
        if result.intent == case.intent:
            correct += 1
            continue
        failures.append({
            "query": case.query,
            "expected": case.intent,
            "predicted": result.intent,
            "confidence": result.confidence,
            "reason": result.reason,
        })
    total = len(cases)
    return IntentEvaluationReport(
        total=total,
        correct=correct,
        accuracy=correct / total if total else 0.0,
        confusion={expected: dict(predicted) for expected, predicted in confusion.items()},
        failures=failures,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate live intent classification accuracy")
    parser.add_argument("golden_set", type=Path)
    parser.add_argument("--minimum-accuracy", type=float, default=0.9)
    args = parser.parse_args()
    cases = load_golden_set(args.golden_set)
    if cases:
        preflight = classify_intent(cases[0].query)
        if preflight.reason.startswith("classification_error:"):
            print(json.dumps({
                "error": "live classifier is unavailable",
                "reason": preflight.reason,
            }, indent=2))
            return 2
    report = evaluate_intents(cases)
    print(json.dumps(asdict(report), indent=2))
    return 0 if report.accuracy >= args.minimum_accuracy else 1


if __name__ == "__main__":
    raise SystemExit(main())
