"""Route a tracked value into the right column, and infer its metadata.

This is what makes the field set dynamic: nothing here knows the name of any
particular field. `log.track(retrieval_hit_rate=0.82)` on a name that has never
been seen lands in `value_num`, registers itself in `field_defs`, and shows up
in the UI -- no migration, no code change.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.engine import Connection

from app.core.db import dumps, q

TEXT_MAX = 512

# Suffix -> unit. Checked longest-first so '_ms' never shadows '_bytes'.
_UNIT_BY_SUFFIX: list[tuple[str, str]] = [
    ("_ms", "ms"),
    ("_seconds", "s"),
    ("_bytes", "B"),
    ("_tokens", "tok"),
    ("_usd", "usd"),
    ("_pct", "%"),
    ("_percent", "%"),
]
_UNIT_BY_KEYWORD: list[tuple[str, str]] = [
    ("token", "tok"),
    ("cost", "usd"),
    ("latency", "ms"),
]

# Fields that mean "how much" accumulate across a run; fields that mean
# "how good" average; everything else keeps its most recent value.
_SUM_HINTS = (
    "_ms", "_tokens", "_bytes", "_count", "cost", "latency", "token",
    "_calls", "retries", "_failures", "_errors", "_chars",
)
_AVG_HINTS = ("score", "confidence", "_rate", "_ratio", "_pct", "_percent")


def infer_unit(name: str) -> str | None:
    lowered = name.lower()
    for suffix, unit in _UNIT_BY_SUFFIX:
        if lowered.endswith(suffix):
            return unit
    for keyword, unit in _UNIT_BY_KEYWORD:
        if keyword in lowered:
            return unit
    return None


def infer_aggregate(name: str, kind: str) -> str:
    if kind not in ("number", "bool"):
        return "last"
    lowered = name.lower()
    if any(hint in lowered for hint in _AVG_HINTS):
        return "avg"
    if any(hint in lowered for hint in _SUM_HINTS):
        return "sum"
    return "last"


def route_value(name: str, value: Any) -> dict[str, Any]:
    """Split an arbitrary Python value into (value_text, value_num, value_json).

    Accepts a bare scalar, or ``{"v": <value>, "unit": "ms"}`` when the caller
    wants to state the unit explicitly rather than let it be inferred.
    """
    unit: str | None = None

    if isinstance(value, dict) and "v" in value and set(value) <= {"v", "unit"}:
        unit = value.get("unit")
        value = value["v"]

    text_val: str | None = None
    num_val: Decimal | None = None
    json_val: Any = None

    if value is None:
        kind = "text"
    elif isinstance(value, bool):
        # bool before int: bool is a subclass of int in Python
        kind, num_val, text_val = "bool", Decimal(1 if value else 0), str(value).lower()
    elif isinstance(value, (int, float, Decimal)):
        kind = "number"
        try:
            num_val = Decimal(str(value))
        except (InvalidOperation, ValueError):
            kind, text_val = "text", str(value)[:TEXT_MAX]
    elif isinstance(value, (dict, list)):
        kind, json_val = "json", value
    else:
        kind, text_val = "text", str(value)[:TEXT_MAX]
        # a numeric-looking string is still worth making aggregatable
        try:
            num_val = Decimal(text_val)
            kind = "number"
        except (InvalidOperation, ValueError):
            pass

    return {
        "name": name,
        "kind": kind,
        "value_text": text_val,
        "value_num": num_val,
        "value_json": json_val,
        "unit": unit or infer_unit(name),
    }


_UPSERT_DEF = q(
    """
    INSERT INTO field_defs (name, label, kind, unit, aggregate, use_count)
    VALUES (:name, :label, :kind, :unit, :aggregate, :n)
    ON DUPLICATE KEY UPDATE
      use_count    = use_count + VALUES(use_count),
      last_seen_at = CURRENT_TIMESTAMP(6),
      -- only fill in metadata the operator has not already customised
      unit         = COALESCE(unit, VALUES(unit)),
      kind         = IF(kind = 'text' AND VALUES(kind) <> 'text', VALUES(kind), kind)
    """
)


def register_fields(conn: Connection, routed: list[dict[str, Any]]) -> None:
    """Upsert field_defs for every name seen in this batch."""
    counts: dict[str, dict[str, Any]] = {}
    for item in routed:
        entry = counts.setdefault(
            item["name"],
            {
                "name": item["name"],
                "label": item["name"].replace("_", " "),
                "kind": item["kind"],
                "unit": item["unit"],
                "aggregate": infer_aggregate(item["name"], item["kind"]),
                "n": 0,
            },
        )
        entry["n"] += 1
        if entry["kind"] == "text" and item["kind"] != "text":
            entry["kind"] = item["kind"]
            entry["aggregate"] = infer_aggregate(item["name"], item["kind"])

    for entry in counts.values():
        conn.execute(_UPSERT_DEF, entry)


_INSERT_FIELD = q(
    """
    INSERT INTO tracked_fields
      (run_id, log_id, seq, name, value_text, value_num, value_json, unit, ts)
    VALUES
      (:run_id, :log_id, :seq, :name, :value_text, :value_num,
       CAST(:value_json AS JSON), :unit, :ts)
    ON DUPLICATE KEY UPDATE
      log_id     = VALUES(log_id),
      value_text = VALUES(value_text),
      value_num  = VALUES(value_num),
      value_json = VALUES(value_json),
      unit       = VALUES(unit),
      ts         = VALUES(ts)
    """
)


def insert_fields(conn: Connection, rows: list[dict[str, Any]]) -> int:
    """Insert tracked_fields rows. Re-POSTing the same batch is a no-op."""
    if not rows:
        return 0
    payload = [
        {**row, "value_json": dumps(row["value_json"])} for row in rows
    ]
    conn.execute(_INSERT_FIELD, payload)
    return len(payload)
