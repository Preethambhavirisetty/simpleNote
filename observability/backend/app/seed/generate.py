"""Generate demo runs by POSTing through the real API.

Writing through the API rather than straight to MySQL means the seeder doubles
as an integration test of the ingest path -- including the replay behaviour,
which it exercises deliberately via --replay.

    python -m app.seed.generate --seed 42 --runs 200 --days 7
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from app.seed import scenarios

PINNED_DEFAULTS = [
    ("playbook", 10, "last"),
    ("resource", 20, "last"),
    ("operation", 30, "last"),
    ("llm_latency_ms", 40, "sum"),
    ("input_tokens", 50, "sum"),
    ("tool_latency_ms", 60, "sum"),
    ("cost_usd", 70, "sum"),
]


def _weighted_choice(rng: random.Random) -> str:
    total = sum(w for _, w in scenarios.SCENARIOS)
    pick = rng.uniform(0, total)
    upto = 0.0
    for name, weight in scenarios.SCENARIOS:
        upto += weight
        if pick <= upto:
            return name
    return scenarios.SCENARIOS[0][0]


def _start_time(rng: random.Random, base: datetime, days: int) -> datetime:
    """Spread runs over N days on a diurnal curve (busy 9-18 local)."""
    day_offset = rng.uniform(0, days)
    hour = min(23.999, max(0.0, rng.normalvariate(13.5, 3.6)))
    when = base - timedelta(days=day_offset)
    return when.replace(
        hour=int(hour),
        minute=rng.randint(0, 59),
        second=rng.randint(0, 59),
        microsecond=rng.randint(0, 999_999),
    )


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed demo agent runs")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8000")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--batch", type=int, default=40, help="log lines per POST")
    ap.add_argument(
        "--replay",
        type=float,
        default=0.05,
        help="fraction of batches to POST twice, proving idempotency",
    )
    ap.add_argument("--conversations", type=int, default=0,
                    help="0 = derive from run count (about 1 in 3 runs continues one)")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    base = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    client = httpx.Client(base_url=args.endpoint.rstrip("/"), timeout=30.0)
    try:
        client.get("/health").raise_for_status()
    except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
        print(f"cannot reach {args.endpoint}: {exc}", file=sys.stderr)
        return 1

    n_convs = args.conversations or max(1, math.ceil(args.runs / 1.5))
    conv_ids = [f"conv-{i:04d}" for i in range(n_convs)]

    totals = {"runs": 0, "logs": 0, "tracked": 0, "duplicates": 0}

    for i in range(args.runs):
        scenario = _weighted_choice(rng)
        started = _start_time(rng, base, args.days)
        built = scenarios.build(scenario, rng, started)

        run_key = uuid.UUID(int=rng.getrandbits(128)).hex
        conversation_id = rng.choice(conv_ids)

        client.post(
            "/api/v1/runs",
            json={
                "run_key": run_key,
                "conversation_id": conversation_id,
                "question": built["question"],
                "started_at": started.isoformat(),
                "metadata": {
                    "env": rng.choice(["dev", "staging", "prod"]),
                    "agent_version": rng.choice(["2.0.4", "2.1.0", "2.1.1"]),
                    "scenario": scenario,
                },
            },
        ).raise_for_status()

        for chunk in _chunks(built["logs"], args.batch):
            # deliberately shuffle within the batch: seq, not arrival order,
            # is what the server orders by
            shuffled = list(chunk)
            rng.shuffle(shuffled)
            resp = client.post(
                f"/api/v1/runs/{run_key}/logs", json={"logs": shuffled}
            )
            resp.raise_for_status()
            body = resp.json()
            totals["logs"] += body["accepted"]
            totals["tracked"] += body["tracked"]

            if rng.random() < args.replay:
                replay = client.post(
                    f"/api/v1/runs/{run_key}/logs", json={"logs": shuffled}
                ).json()
                totals["duplicates"] += replay["duplicates"]

        if built["status"] != "running":
            client.post(
                f"/api/v1/runs/{run_key}/finish",
                json={
                    "status": built["status"],
                    "final_answer": built["final_answer"],
                    "error_message": built["error_message"],
                    "ended_at": built["ended_at"].isoformat(),
                },
            ).raise_for_status()

        totals["runs"] += 1
        if totals["runs"] % 25 == 0:
            print(f"  {totals['runs']}/{args.runs} runs", flush=True)

    for name, order, aggregate in PINNED_DEFAULTS:
        client.patch(
            f"/api/v1/fields/{name}",
            json={"pinned": True, "display_order": order, "aggregate": aggregate},
        )

    print(
        f"seeded {totals['runs']} runs, {totals['logs']} log lines, "
        f"{totals['tracked']} tracked values, "
        f"{totals['duplicates']} replayed lines correctly deduplicated"
    )
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
