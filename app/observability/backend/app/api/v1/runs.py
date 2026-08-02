"""Read path for runs: list, detail, tracked fields, phases."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import bindparam
from sqlalchemy.engine import Connection

from app.core.db import as_json, as_num, get_conn, iso, q
from app.services.filters import FilterError, build_exists_clauses, parse_field_filters

router = APIRouter(tags=["runs"])

RUN_COLS = """
    r.id, r.run_key, r.conversation_id, r.question, r.final_answer, r.status,
    r.error_message, r.started_at, r.ended_at, r.duration_ms, r.log_count,
    r.error_count, r.max_seq, r.metadata_json
"""


def _run_row(row: Any) -> dict:
    return {
        "id": row["id"],
        "run_key": row["run_key"],
        "conversation_id": row["conversation_id"],
        "question": row["question"],
        "final_answer": row["final_answer"],
        "status": row["status"],
        "error_message": row["error_message"],
        "started_at": iso(row["started_at"]),
        "ended_at": iso(row["ended_at"]),
        "duration_ms": row["duration_ms"],
        "log_count": row["log_count"],
        "error_count": row["error_count"],
        "max_seq": row["max_seq"],
        "metadata": as_json(row["metadata_json"]),
    }


def _field_value(row: Any) -> Any:
    if row["value_json"] is not None:
        return as_json(row["value_json"])
    if row["value_num"] is not None:
        return as_num(row["value_num"])
    return row["value_text"]


def _decode_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    ts, _, rid = cursor.partition("|")
    try:
        return datetime.fromisoformat(ts), int(rid)
    except (ValueError, TypeError):
        raise HTTPException(400, "malformed cursor")


@router.get("/runs")
def list_runs(
    request: Request,
    conn: Connection = Depends(get_conn),
    status: str | None = None,
    conversation_id: str | None = None,
    q_text: str | None = Query(default=None, alias="q"),
    phase: str | None = None,
    has_errors: bool | None = None,
    since: datetime | None = Query(default=None, alias="from"),
    until: datetime | None = Query(default=None, alias="to"),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Recent runs, newest first.

    Beyond the fixed filters, any tracked field can be filtered on directly:
    `?f.playbook=incident_triage&f.llm_latency_ms.gt=800&f.score.lt=0.5`.
    """
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit + 1}

    if status:
        where.append("r.status = :status")
        params["status"] = status
    if conversation_id:
        where.append("r.conversation_id = :cid")
        params["cid"] = conversation_id
    if has_errors is not None:
        where.append("r.error_count > 0" if has_errors else "r.error_count = 0")
    if since:
        where.append("r.started_at >= :since")
        params["since"] = since
    if until:
        where.append("r.started_at <= :until")
        params["until"] = until
    if q_text:
        # LIKE rather than MATCH: short agent phrases and partial words are
        # exactly what people type here, and FULLTEXT drops both
        where.append("(r.question LIKE :qtext OR r.final_answer LIKE :qtext)")
        params["qtext"] = f"%{q_text}%"
    if phase:
        where.append(
            "EXISTS (SELECT 1 FROM logs lp WHERE lp.run_id = r.id AND lp.phase = :phase)"
        )
        params["phase"] = phase

    try:
        field_filters = parse_field_filters(request.query_params)
        clauses, field_params = build_exists_clauses(field_filters)
    except FilterError as exc:
        raise HTTPException(400, str(exc)) from exc
    where.extend(clauses)
    params.update(field_params)

    if (decoded := _decode_cursor(cursor)) is not None:
        params["cur_ts"], params["cur_id"] = decoded
        where.append(
            "(r.started_at < :cur_ts OR (r.started_at = :cur_ts AND r.id < :cur_id))"
        )

    rows = conn.execute(
        q(
            f"""SELECT {RUN_COLS} FROM runs r
                 WHERE {' AND '.join(where)}
                 ORDER BY r.started_at DESC, r.id DESC
                 LIMIT :limit"""
        ),
        params,
    ).mappings().all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [_run_row(r) for r in rows]

    # attach pinned field values so the list can show them as columns
    if items:
        pinned = conn.execute(
            q(
                """SELECT tf.run_id, tf.name, tf.value_text, tf.value_num,
                          tf.value_json, tf.unit, tf.seq
                     FROM tracked_fields tf
                     JOIN field_defs fd ON fd.name = tf.name AND fd.pinned = 1
                    WHERE tf.run_id IN :ids
                    ORDER BY tf.run_id, tf.name, tf.seq"""
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": [i["id"] for i in items]},
        ).mappings().all()
        by_run: dict[int, dict[str, Any]] = {}
        for row in pinned:
            by_run.setdefault(row["run_id"], {})[row["name"]] = _field_value(row)
        for item in items:
            item["fields"] = by_run.get(item["id"], {})

    next_cursor = None
    if has_more and items:
        last = rows[-1]
        next_cursor = f"{last['started_at'].isoformat()}|{last['id']}"

    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


@router.get("/runs/{run_key}")
def get_run(run_key: str, conn: Connection = Depends(get_conn)) -> dict:
    row = conn.execute(
        q(f"SELECT {RUN_COLS} FROM runs r WHERE r.run_key = :k"), {"k": run_key}
    ).mappings().first()
    if row is None:
        raise HTTPException(404, f"unknown run_key {run_key!r}")

    run = _run_row(row)
    run["fields"] = _summarised_fields(conn, run["id"])
    return run


def _summarised_fields(conn: Connection, run_id: int) -> list[dict]:
    """Collapse each tracked field to one value using its declared aggregate."""
    rows = conn.execute(
        q(
            """SELECT tf.name, tf.value_text, tf.value_num, tf.value_json,
                      tf.unit, tf.seq, tf.log_id,
                      fd.label, fd.kind, fd.aggregate, fd.pinned, fd.display_order
                 FROM tracked_fields tf
                 LEFT JOIN field_defs fd ON fd.name = tf.name
                WHERE tf.run_id = :r
                ORDER BY tf.name, tf.seq"""
        ),
        {"r": run_id},
    ).mappings().all()

    grouped: dict[str, list[Any]] = {}
    meta: dict[str, dict] = {}
    for row in rows:
        grouped.setdefault(row["name"], []).append(row)
        meta.setdefault(
            row["name"],
            {
                "label": row["label"] or row["name"].replace("_", " "),
                "kind": row["kind"] or "text",
                "aggregate": row["aggregate"] or "last",
                "unit": row["unit"],
                "pinned": bool(row["pinned"]),
                "display_order": row["display_order"] if row["display_order"] is not None else 100,
            },
        )

    out = []
    for name, entries in grouped.items():
        info = meta[name]
        nums = [as_num(e["value_num"]) for e in entries if e["value_num"] is not None]
        agg = info["aggregate"]

        if nums and agg in ("sum", "avg", "max", "min"):
            value = {
                "sum": sum(nums),
                "avg": sum(nums) / len(nums),
                "max": max(nums),
                "min": min(nums),
            }[agg]
            if isinstance(value, float):
                value = round(value, 6)
        elif agg == "count":
            value = len(entries)
        elif agg == "first":
            value = _field_value(entries[0])
        else:
            value = _field_value(entries[-1])

        out.append(
            {
                "name": name,
                "label": info["label"],
                "kind": info["kind"],
                "unit": info["unit"],
                "aggregate": agg,
                "pinned": info["pinned"],
                "display_order": info["display_order"],
                "value": value,
                "count": len(entries),
                "values": [
                    {
                        "seq": e["seq"],
                        "log_id": e["log_id"],
                        "value": _field_value(e),
                    }
                    for e in entries
                ],
            }
        )

    out.sort(key=lambda f: (not f["pinned"], f["display_order"], f["name"]))
    return out


@router.get("/runs/{run_key}/fields")
def run_fields(run_key: str, conn: Connection = Depends(get_conn)) -> dict:
    row = conn.execute(
        q("SELECT id FROM runs WHERE run_key = :k"), {"k": run_key}
    ).first()
    if row is None:
        raise HTTPException(404, f"unknown run_key {run_key!r}")
    return {"items": _summarised_fields(conn, int(row[0]))}


@router.get("/runs/{run_key}/phases")
def run_phases(run_key: str, conn: Connection = Depends(get_conn)) -> dict:
    rows = conn.execute(
        q(
            """SELECT l.phase,
                      COUNT(*) AS log_count,
                      SUM(l.level = 'ERROR') AS error_count,
                      COALESCE(SUM(l.duration_ms), 0) AS duration_ms,
                      MIN(l.seq) AS first_seq
                 FROM logs l
                 JOIN runs r ON r.id = l.run_id
                WHERE r.run_key = :k
             GROUP BY l.phase
             ORDER BY first_seq"""
        ),
        {"k": run_key},
    ).mappings().all()
    return {
        "items": [
            {
                "phase": r["phase"],
                "log_count": int(r["log_count"]),
                "error_count": int(r["error_count"] or 0),
                "duration_ms": int(r["duration_ms"] or 0),
                "first_seq": int(r["first_seq"]),
            }
            for r in rows
        ]
    }


@router.get("/conversations/{conversation_id}/runs")
def conversation_runs(
    conversation_id: str, conn: Connection = Depends(get_conn)
) -> dict:
    rows = conn.execute(
        q(
            f"""SELECT {RUN_COLS} FROM runs r
                 WHERE r.conversation_id = :cid
                 ORDER BY r.started_at ASC, r.id ASC"""
        ),
        {"cid": conversation_id},
    ).mappings().all()
    return {"items": [_run_row(r) for r in rows]}


@router.delete("/runs/{run_key}")
def delete_run(run_key: str, conn: Connection = Depends(get_conn)) -> dict:
    with conn.begin():
        result = conn.execute(q("DELETE FROM runs WHERE run_key = :k"), {"k": run_key})
        if result.rowcount == 0:
            raise HTTPException(404, f"unknown run_key {run_key!r}")
    return {"deleted": run_key}
