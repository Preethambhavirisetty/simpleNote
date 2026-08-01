"""Turn `?f.<name>[.<op>]=<value>` query params into SQL against tracked_fields.

Each filter becomes a correlated EXISTS, which lets you combine any number of
them without a join explosion. The lookup is served by
`idx_tf_run_name (run_id, name, seq)`; numeric comparisons then evaluate
`value_num` and text comparisons `value_text`, both of which are real columns
rather than JSON extractions.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

_NAME_OK = re.compile(r"[A-Za-z0-9_.\-]+")

NUMERIC_OPS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "ne": "<>", "eq": "="}
TEXT_OPS = {"eq": "=", "ne": "<>"}
ALL_OPS = set(NUMERIC_OPS) | {"contains", "in", "exists", "isnull"}

MAX_FILTERS = 12


class FilterError(ValueError):
    pass


def _as_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def parse_field_filters(params: Any) -> list[tuple[str, str, str]]:
    """Extract (name, op, value) triples from `f.name` / `f.name.op` params."""
    out: list[tuple[str, str, str]] = []
    for key in params.keys():
        if not key.startswith("f."):
            continue
        rest = key[2:]
        if not rest:
            continue
        name, _, maybe_op = rest.rpartition(".")
        if name and maybe_op in ALL_OPS:
            op = maybe_op
        else:
            name, op = rest, "eq"
        if not name:
            continue
        # Dots are allowed so namespaced names ('llm.latency_ms') work; the
        # trailing-segment check above already distinguishes those from an
        # operator suffix. The name is always bound as a parameter, never
        # interpolated, so this is a sanity check rather than an injection guard.
        if len(name) > 64 or not _NAME_OK.fullmatch(name):
            raise FilterError(f"invalid tracked field name: {name!r}")
        for value in params.getlist(key):
            out.append((name, op, value))
    if len(out) > MAX_FILTERS:
        raise FilterError(f"too many field filters (max {MAX_FILTERS})")
    return out


def build_exists_clauses(
    filters: list[tuple[str, str, str]], alias: str = "r"
) -> tuple[list[str], dict[str, Any]]:
    """Return (sql_fragments, bind_params) for the parsed filters."""
    clauses: list[str] = []
    params: dict[str, Any] = {}

    for i, (name, op, raw) in enumerate(filters):
        n_key, v_key = f"tf_name_{i}", f"tf_val_{i}"
        params[n_key] = name

        if op == "exists":
            predicate = "1=1" if raw.lower() not in ("0", "false", "no") else None
            if predicate is None:
                clauses.append(
                    f"NOT EXISTS (SELECT 1 FROM tracked_fields tf{i} "
                    f"WHERE tf{i}.run_id = {alias}.id AND tf{i}.name = :{n_key})"
                )
                continue
        elif op == "isnull":
            predicate = "tf{i}.value_text IS NULL AND tf{i}.value_num IS NULL".format(i=i)
        elif op == "contains":
            predicate = f"tf{i}.value_text LIKE :{v_key}"
            params[v_key] = f"%{raw}%"
        elif op == "in":
            values = [v for v in (s.strip() for s in raw.split(",")) if v]
            if not values:
                raise FilterError(f"empty 'in' list for field {name!r}")
            keys = []
            for j, value in enumerate(values):
                key = f"{v_key}_{j}"
                params[key] = value
                keys.append(f":{key}")
            predicate = f"tf{i}.value_text IN ({', '.join(keys)})"
        else:
            sql_op = NUMERIC_OPS[op]
            number = _as_decimal(raw)
            if number is not None:
                predicate = f"tf{i}.value_num {sql_op} :{v_key}"
                params[v_key] = number
            elif op in TEXT_OPS:
                predicate = f"tf{i}.value_text {TEXT_OPS[op]} :{v_key}"
                params[v_key] = raw
            else:
                raise FilterError(
                    f"operator '{op}' on field {name!r} needs a number, got {raw!r}"
                )

        clauses.append(
            f"EXISTS (SELECT 1 FROM tracked_fields tf{i} "
            f"WHERE tf{i}.run_id = {alias}.id AND tf{i}.name = :{n_key} "
            f"AND {predicate})"
        )

    return clauses, params
