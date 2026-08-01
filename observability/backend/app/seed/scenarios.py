"""Weighted run templates.

Scenario-driven rather than a random walk: random events produce traces that
do not look like anything a real agent would emit, and the point of the demo
data is to make the UI legible.
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from app.seed import vocab

# (name, weight)
SCENARIOS = [
    ("happy_simple", 30),
    ("happy_multi_tool", 15),
    ("tool_retry_success", 12),
    ("validation_then_repair", 10),
    ("ambiguous_resolution", 8),
    ("llm_failure_fatal", 7),
    ("tool_error_partial", 6),
    ("long_memory_run", 6),
    ("abandoned_run", 4),
]


class Builder:
    """Accumulates log lines for one run, assigning seq and timestamps."""

    def __init__(self, rng: random.Random, start):
        self.rng = rng
        self.clock = start
        self.seq = 0
        self.lines: list[dict[str, Any]] = []

    def advance(self, ms: float) -> None:
        self.clock += timedelta(milliseconds=max(0.0, ms))

    def add(
        self,
        level: str,
        phase: str,
        message: str,
        *,
        data: dict | None = None,
        duration_ms: int | None = None,
        track: dict | None = None,
        gap_ms: float = 0.0,
        source: str | None = None,
    ) -> None:
        self.advance(gap_ms or self.rng.uniform(1, 18))
        self.seq += 1
        self.lines.append(
            {
                "seq": self.seq,
                "ts": self.clock.isoformat(),
                "level": level,
                "phase": phase,
                "message": message,
                "source": source or f"{phase}.py:{self.rng.randint(20, 320)}",
                "data": data,
                "duration_ms": duration_ms,
                "track": track or None,
            }
        )

    def chatter(self, phase: str, n: int = 2, **ctx: Any) -> None:
        for _ in range(n):
            template = self.rng.choice(vocab.DEBUG_CHATTER)
            self.add(
                "DEBUG",
                phase,
                template.format(
                    n=self.rng.randint(1, 99),
                    hit=self.rng.choice(["hit", "miss"]),
                    key=f"cat:{self.rng.randint(1000, 9999)}",
                    tool=self.rng.choice([o[3] for o in vocab.OPERATIONS]),
                    ns=ctx.get("ns", "prod"),
                    svc=ctx.get("svc", "checkout-api"),
                ),
            )


def _lognormal_ms(rng: random.Random, mu: float, sigma: float = 0.5) -> int:
    """Latencies are log-normal in practice; a uniform draw looks obviously fake."""
    import math

    return max(1, int(math.exp(rng.normalvariate(math.log(mu), sigma))))


def _llm_call(b: Builder, ctx: dict, purpose: str, *, fail: bool = False) -> None:
    model = ctx["model"]
    latency = _lognormal_ms(b.rng, 900)
    inp = b.rng.randint(1200, 9000)
    out = b.rng.randint(60, 700)
    # every call after the first reuses the prompt prefix
    cached = 0 if ctx["llm_calls"] == 0 else b.rng.randint(2000, 20000)
    ctx["llm_calls"] += 1

    b.add("INFO", "llm", f"calling {model} for {purpose}", gap_ms=b.rng.uniform(4, 40))
    b.chatter("llm", 1, **ctx)

    if fail:
        b.add(
            "ERROR",
            "llm",
            f"{model} request timed out after {latency}ms",
            duration_ms=latency,
            data={"purpose": purpose, "attempt": 1},
            track={
                "model": model,
                "llm_latency_ms": latency,
                "llm_error": "TimeoutError",
                "llm_calls": 1,
            },
        )
        return

    cost = round((inp * 3 + out * 15 + cached * 0.3) / 1_000_000, 6)
    b.add(
        "DEBUG",
        "llm",
        f"{model} responded ({out} output tokens)",
        duration_ms=latency,
        data={"purpose": purpose, "stop_reason": b.rng.choice(["end_turn", "tool_use"])},
        track={
            "model": model,
            "llm_latency_ms": latency,
            "input_tokens": inp,
            "output_tokens": out,
            "cached_tokens": cached,
            "cost_usd": cost,
            "llm_calls": 1,
        },
        gap_ms=latency,
    )


def _tool_call(
    b: Builder, ctx: dict, tool: str, *, outcome: str = "ok", attempt: int = 1
) -> int:
    latency = _lognormal_ms(b.rng, 150 if outcome == "ok" else 900)
    args = {"namespace": ctx["ns"], "name": ctx["svc"]}
    b.add(
        "INFO",
        "tool",
        f"calling {tool}" + (f" (attempt {attempt})" if attempt > 1 else ""),
        data={"arguments": args},
        gap_ms=b.rng.uniform(2, 20),
    )
    if outcome == "ok":
        rows = b.rng.randint(1, 40)
        b.add(
            "DEBUG",
            "tool",
            f"{tool} returned {rows} rows",
            duration_ms=latency,
            data={"http_status": 200},
            track={
                "tool_name": tool,
                "tool_latency_ms": latency,
                "tool_rows": rows,
                "tool_calls": 1,
            },
            gap_ms=latency,
        )
    else:
        code = 429 if outcome == "rate_limited" else 504
        b.add(
            "ERROR",
            "tool",
            f"{tool} failed with HTTP {code}",
            duration_ms=latency,
            data={"http_status": code, "attempt": attempt},
            track={
                "tool_name": tool,
                "tool_latency_ms": latency,
                "tool_error": f"HTTP{code}",
                "tool_calls": 1,
            },
            gap_ms=latency,
        )
    return latency


def _resolve_phase(b: Builder, ctx: dict, *, ambiguous: bool = False) -> None:
    rng = b.rng
    b.add("INFO", "resolve_playbook", "classifying question intent")
    b.chatter("resolve_playbook", 2, **ctx)
    _llm_call(b, ctx, "playbook selection")

    if ambiguous:
        top, second = 0.58, 0.55
        candidates = rng.sample([p[0] for p in vocab.PLAYBOOKS], 4)
        b.add(
            "WARN",
            "resolve_playbook",
            f"top two candidates within {top - second:.2f} — asking for confirmation",
            data={"candidates": candidates},
            track={
                "playbook": ctx["playbook"],
                "playbook_score": top,
                "playbook_margin": round(top - second, 4),
                "candidate_count": len(candidates),
                "needed_confirmation": True,
            },
        )
    else:
        score = round(rng.uniform(0.78, 0.98), 4)
        b.add(
            "INFO",
            "resolve_playbook",
            f"selected playbook {ctx['playbook']}",
            track={
                "playbook": ctx["playbook"],
                "playbook_score": score,
                "candidate_count": rng.randint(2, 5),
            },
        )

    b.chatter("resolve_resource", 1, **ctx)
    b.add(
        "INFO",
        "resolve_resource",
        f"resolved resource {ctx['resource']}",
        track={
            "resource": ctx["resource"],
            "resource_score": round(rng.uniform(0.8, 0.99), 4),
        },
    )
    b.add(
        "INFO",
        "resolve_operation",
        f"resolved operation {ctx['operation']}"
        + (" (mutating)" if ctx["mutating"] else ""),
        track={
            "operation": ctx["operation"],
            "operation_mutating": ctx["mutating"],
            "operation_score": round(rng.uniform(0.75, 0.99), 4),
        },
    )


def _memory_phase(b: Builder, ctx: dict, turns: int = 1) -> None:
    b.add(
        "DEBUG",
        "memory",
        f"loaded conversation memory ({turns} prior turns)",
        track={
            "conversation_state": {
                "turn": turns,
                "slots": {"service": ctx["svc"], "namespace": ctx["ns"]},
                "pending_confirmation": ctx.get("mutating", False),
            },
            "memory": {
                "facts": [
                    f"{ctx['svc']} runs in {ctx['ns']}",
                    f"last incident on {ctx['svc']} was 6 days ago",
                ][: 1 + turns % 2],
                "entities": [ctx["svc"], ctx["ns"]],
            },
            "memory_turns": turns,
        },
    )


def _respond(b: Builder, ctx: dict) -> str:
    _llm_call(b, ctx, "final answer synthesis")
    answer = vocab.FINAL_ANSWERS[ctx["playbook"]].format(
        svc=ctx["svc"], ns=ctx["ns"], code=ctx["code"]
    )
    b.add("INFO", "respond", "returning answer to user", track={"answer_chars": len(answer)})
    return answer


def build(scenario: str, rng: random.Random, start) -> dict[str, Any]:
    """Produce one complete run: question, log lines, final status."""
    playbook, question_tpl = rng.choice(vocab.PLAYBOOKS)
    operation, resource, mutating, tool = rng.choice(vocab.OPERATIONS)
    ctx = {
        "playbook": playbook,
        "resource": resource,
        "operation": operation,
        "mutating": mutating,
        "tool": tool,
        "svc": rng.choice(vocab.SERVICES),
        "ns": rng.choice(vocab.NAMESPACES),
        "code": rng.choice(vocab.CODES),
        "model": rng.choice(vocab.MODELS),
        "llm_calls": 0,
    }
    question = question_tpl.format(svc=ctx["svc"], code=ctx["code"])

    b = Builder(rng, start)
    b.add("INFO", "intake", f"received question: {question}", track={"scenario": scenario})
    _memory_phase(b, ctx, turns=rng.randint(0, 3))

    status, answer, error = "ok", None, None

    if scenario == "abandoned_run":
        _resolve_phase(b, ctx)
        b.add("INFO", "tool", f"calling {tool}")
        b.chatter("tool", 2, **ctx)
        return _done(b, question, ctx, "running", None, None, scenario)

    if scenario == "llm_failure_fatal":
        b.add("INFO", "resolve_playbook", "classifying question intent")
        _llm_call(b, ctx, "playbook selection", fail=True)
        b.add(
            "ERROR",
            "respond",
            "giving up after upstream model timeout",
            track={"failure_phase": "llm", "failed": True},
        )
        return _done(b, question, ctx, "error", None, "LLM request timed out", scenario)

    _resolve_phase(b, ctx, ambiguous=(scenario == "ambiguous_resolution"))

    if scenario == "validation_then_repair":
        b.add(
            "ERROR",
            "validate",
            "argument validation failed: /args/namespace is required",
            data={"validator": "RolloutUndoArgs", "expected": "string", "actual": None},
            track={
                "validation_failures": 1,
                "validation_field": "/args/namespace",
                "validation_rule": "required",
            },
        )
        b.add("INFO", "validate", "re-prompting model with the schema error")
        _llm_call(b, ctx, "argument repair")
        b.add("INFO", "validate", "arguments valid on second attempt", track={"repaired": True})
        _tool_call(b, ctx, tool)

    elif scenario == "tool_retry_success":
        for attempt in (1, 2):
            _tool_call(b, ctx, tool, outcome="rate_limited", attempt=attempt)
            backoff = 250 * attempt
            b.add(
                "WARN",
                "tool",
                f"backing off {backoff}ms before retry {attempt + 1}/3",
                track={"retries": 1, "retry_backoff_ms": backoff},
                gap_ms=backoff,
            )
        _tool_call(b, ctx, tool, attempt=3)

    elif scenario == "tool_error_partial":
        _tool_call(b, ctx, tool)
        other = rng.choice([o[3] for o in vocab.OPERATIONS if o[3] != tool])
        _tool_call(b, ctx, other, outcome="timeout")
        b.add(
            "WARN",
            "respond",
            "answering from partial data — one tool did not return",
            track={"partial_result": True},
        )
        status = "ok"

    elif scenario == "happy_multi_tool":
        tools = rng.sample([o[3] for o in vocab.OPERATIONS], 4)
        for t in tools:
            b.chatter("tool", 1, **ctx)
            _tool_call(b, ctx, t)

    elif scenario == "long_memory_run":
        for turn in range(1, 6):
            _memory_phase(b, ctx, turns=turn)
            b.chatter("memory", 2, **ctx)
            if turn % 2 == 0:
                _llm_call(b, ctx, f"summarise turn {turn}")
        _tool_call(b, ctx, tool)

    else:  # happy_simple
        _tool_call(b, ctx, tool)

    answer = _respond(b, ctx)
    return _done(b, question, ctx, status, answer, error, scenario)


def _done(b, question, ctx, status, answer, error, scenario) -> dict[str, Any]:
    return {
        "question": question,
        "logs": b.lines,
        "status": status,
        "final_answer": answer,
        "error_message": error,
        "ended_at": b.clock,
        "scenario": scenario,
        "conversation_id": ctx.get("conversation_id"),
    }
