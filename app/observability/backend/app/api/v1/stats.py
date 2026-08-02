"""Aggregates over runs and tracked fields.

`/stats/fields/{name}` is the payoff for keeping tracked values in real indexed
columns: "avg llm_latency_ms grouped by playbook" is one query, not a scan.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import Connection

from app.core.db import as_num, get_conn, iso, q

router = APIRouter(tags=["stats"])

AGGREGATES = {
    "avg": "AVG(tf.value_num)",
    "sum": "SUM(tf.value_num)",
    "min": "MIN(tf.value_num)",
    "max": "MAX(tf.value_num)",
    "count": "COUNT(*)",
}
BUCKETS = {
    "hour": "DATE_FORMAT(tf.ts, '%Y-%m-%d %H:00:00')",
    "day": "DATE(tf.ts)",
}


def _window(since: datetime | None, until: datetime | None, col: str) -> tuple[str, dict]:
    where, params = [], {}
    if since:
        where.append(f"{col} >= :since")
        params["since"] = since
    if until:
        where.append(f"{col} <= :until")
        params["until"] = until
    return (" AND ".join(where) if where else "1=1"), params


@router.get("/stats/overview")
def overview(
    conn: Connection = Depends(get_conn),
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
) -> dict:
    clause, params = _window(since, until, "r.started_at")

    totals = conn.execute(
        q(
            f"""SELECT COUNT(*) AS runs,
                       SUM(r.status = 'ok') AS ok,
                       SUM(r.status = 'error') AS failed,
                       SUM(r.status = 'running') AS running,
                       SUM(r.error_count > 0) AS with_errors,
                       COALESCE(SUM(r.log_count), 0) AS log_lines,
                       COALESCE(AVG(r.duration_ms), 0) AS avg_duration_ms
                  FROM runs r WHERE {clause}"""
        ),
        params,
    ).mappings().first()

    # p50/p95 without window functions: order by duration and pick by offset
    durations = [
        int(row[0])
        for row in conn.execute(
            q(
                f"""SELECT r.duration_ms FROM runs r
                     WHERE {clause} AND r.duration_ms IS NOT NULL
                     ORDER BY r.duration_ms"""
            ),
            params,
        )
    ]

    def pct(p: float) -> int | None:
        if not durations:
            return None
        idx = min(len(durations) - 1, int(round((len(durations) - 1) * p)))
        return durations[idx]

    runs = int(totals["runs"] or 0)
    return {
        "runs": runs,
        "ok": int(totals["ok"] or 0),
        "failed": int(totals["failed"] or 0),
        "running": int(totals["running"] or 0),
        "with_errors": int(totals["with_errors"] or 0),
        "error_rate": round(int(totals["with_errors"] or 0) / runs, 4) if runs else 0,
        "log_lines": int(totals["log_lines"] or 0),
        "avg_duration_ms": int(totals["avg_duration_ms"] or 0),
        "p50_duration_ms": pct(0.50),
        "p95_duration_ms": pct(0.95),
    }


@router.get("/stats/fields/{name}")
def field_stats(
    name: str,
    conn: Connection = Depends(get_conn),
    agg: str = Query(default="avg"),
    group_by: str | None = Query(default=None, description="another tracked field name"),
    bucket: str | None = Query(default=None, description="hour | day"),
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    if agg not in AGGREGATES:
        raise HTTPException(400, f"unknown agg {agg!r}; use one of {sorted(AGGREGATES)}")
    if bucket and bucket not in BUCKETS:
        raise HTTPException(400, f"unknown bucket {bucket!r}; use hour or day")
    if group_by and bucket:
        raise HTTPException(400, "use group_by or bucket, not both")

    clause, params = _window(since, until, "tf.ts")
    params.update({"name": name, "limit": limit})
    expr = AGGREGATES[agg]

    if group_by:
        params["group_by"] = group_by
        sql = f"""
            SELECT g.value_text AS bucket, {expr} AS value, COUNT(*) AS n
              FROM tracked_fields tf
              JOIN tracked_fields g
                ON g.run_id = tf.run_id AND g.name = :group_by
             WHERE tf.name = :name AND {clause}
          GROUP BY g.value_text
          ORDER BY value DESC
             LIMIT :limit
        """
    elif bucket:
        sql = f"""
            SELECT {BUCKETS[bucket]} AS bucket, {expr} AS value, COUNT(*) AS n
              FROM tracked_fields tf
             WHERE tf.name = :name AND {clause}
          GROUP BY bucket
          ORDER BY bucket
             LIMIT :limit
        """
    else:
        sql = f"""
            SELECT NULL AS bucket, {expr} AS value, COUNT(*) AS n
              FROM tracked_fields tf
             WHERE tf.name = :name AND {clause}
        """

    rows = conn.execute(q(sql), params).mappings().all()
    meta = conn.execute(
        q("SELECT label, kind, unit, aggregate FROM field_defs WHERE name = :name"),
        {"name": name},
    ).mappings().first()

    return {
        "name": name,
        "label": (meta or {}).get("label") or name.replace("_", " "),
        "unit": (meta or {}).get("unit"),
        "kind": (meta or {}).get("kind"),
        "agg": agg,
        "group_by": group_by,
        "bucket": bucket,
        "items": [
            {
                "bucket": iso(r["bucket"]) if isinstance(r["bucket"], datetime) else (
                    str(r["bucket"]) if r["bucket"] is not None else None
                ),
                "value": as_num(r["value"]),
                "n": int(r["n"]),
            }
            for r in rows
        ],
    }


@router.get("/stats/timeseries")
def timeseries(
    conn: Connection = Depends(get_conn),
    bucket: str = Query(default="day"),
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
) -> dict:
    if bucket not in ("hour", "day"):
        raise HTTPException(400, "bucket must be hour or day")
    expr = (
        "DATE_FORMAT(r.started_at, '%Y-%m-%d %H:00:00')"
        if bucket == "hour"
        else "DATE(r.started_at)"
    )
    clause, params = _window(since, until, "r.started_at")
    rows = conn.execute(
        q(
            f"""SELECT {expr} AS bucket,
                       COUNT(*) AS runs,
                       SUM(r.status = 'error') AS failed,
                       COALESCE(AVG(r.duration_ms), 0) AS avg_duration_ms
                  FROM runs r WHERE {clause}
              GROUP BY bucket ORDER BY bucket"""
        ),
        params,
    ).mappings().all()
    return {
        "bucket": bucket,
        "items": [
            {
                "bucket": str(r["bucket"]),
                "runs": int(r["runs"]),
                "failed": int(r["failed"] or 0),
                "avg_duration_ms": int(r["avg_duration_ms"] or 0),
            }
            for r in rows
        ],
    }


@router.get("/stats/phases")
def phase_stats(
    conn: Connection = Depends(get_conn),
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
) -> dict:
    clause, params = _window(since, until, "l.ts")
    rows = conn.execute(
        q(
            f"""SELECT l.phase,
                       COUNT(*) AS log_count,
                       SUM(l.level = 'ERROR') AS error_count,
                       COUNT(DISTINCT l.run_id) AS run_count
                  FROM logs l WHERE l.phase IS NOT NULL AND {clause}
              GROUP BY l.phase ORDER BY log_count DESC"""
        ),
        params,
    ).mappings().all()
    return {
        "items": [
            {
                "phase": r["phase"],
                "log_count": int(r["log_count"]),
                "error_count": int(r["error_count"] or 0),
                "run_count": int(r["run_count"]),
            }
            for r in rows
        ]
    }
