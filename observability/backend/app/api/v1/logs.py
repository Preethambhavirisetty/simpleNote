"""The log stream for one run."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam
from sqlalchemy.engine import Connection

from app.core.db import as_json, as_num, get_conn, iso, q

router = APIRouter(tags=["logs"])

LEVEL_ORDER = ["DEBUG", "INFO", "WARN", "ERROR"]


@router.get("/runs/{run_key}/logs")
def run_logs(
    run_key: str,
    conn: Connection = Depends(get_conn),
    level: str | None = Query(default=None, description="minimum level, e.g. WARN"),
    levels: str | None = Query(default=None, description="exact levels, comma separated"),
    phase: str | None = None,
    q_text: str | None = Query(default=None, alias="q"),
    after_seq: int = Query(default=-1, description="for live tail / pagination"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict:
    row = conn.execute(
        q("SELECT id, max_seq FROM runs WHERE run_key = :k"), {"k": run_key}
    ).first()
    if row is None:
        raise HTTPException(404, f"unknown run_key {run_key!r}")
    run_id, max_seq = int(row[0]), int(row[1])

    where = ["l.run_id = :run_id", "l.seq > :after_seq"]
    params: dict[str, Any] = {
        "run_id": run_id,
        "after_seq": after_seq,
        "limit": limit + 1,
    }
    wanted_levels: list[str] | None = None

    if levels:
        wanted_levels = [v.strip().upper() for v in levels.split(",") if v.strip()]
    elif level:
        upper = level.upper()
        if upper not in LEVEL_ORDER:
            raise HTTPException(400, f"unknown level {level!r}")
        wanted_levels = LEVEL_ORDER[LEVEL_ORDER.index(upper) :]

    if wanted_levels:
        unknown = set(wanted_levels) - set(LEVEL_ORDER)
        if unknown:
            raise HTTPException(400, f"unknown level(s): {sorted(unknown)}")
        where.append("l.level IN :levels")
        params["levels"] = wanted_levels

    if phase:
        where.append("l.phase = :phase")
        params["phase"] = phase
    if q_text:
        where.append("(l.message LIKE :qtext OR l.source LIKE :qtext)")
        params["qtext"] = f"%{q_text}%"

    stmt = q(
        f"""SELECT l.id, l.seq, l.ts, l.level, l.phase, l.message, l.source,
                   l.data_json, l.duration_ms
              FROM logs l
             WHERE {' AND '.join(where)}
             ORDER BY l.seq
             LIMIT :limit"""
    )
    if wanted_levels:
        stmt = stmt.bindparams(bindparam("levels", expanding=True))

    rows = conn.execute(stmt, params).mappings().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    ids = [r["id"] for r in rows]
    tracked: dict[int, list[dict]] = {}
    if ids:
        for tf in conn.execute(
            q(
                """SELECT log_id, name, value_text, value_num, value_json, unit
                     FROM tracked_fields
                    WHERE log_id IN :ids
                    ORDER BY name"""
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids},
        ).mappings():
            value = (
                as_json(tf["value_json"])
                if tf["value_json"] is not None
                else as_num(tf["value_num"])
                if tf["value_num"] is not None
                else tf["value_text"]
            )
            tracked.setdefault(tf["log_id"], []).append(
                {"name": tf["name"], "value": value, "unit": tf["unit"]}
            )

    items = [
        {
            "id": r["id"],
            "seq": r["seq"],
            "ts": iso(r["ts"]),
            "level": r["level"],
            "phase": r["phase"],
            "message": r["message"],
            "source": r["source"],
            "data": as_json(r["data_json"]),
            "duration_ms": r["duration_ms"],
            "tracked": tracked.get(r["id"], []),
        }
        for r in rows
    ]

    return {
        "items": items,
        "has_more": has_more,
        "last_seq": items[-1]["seq"] if items else after_seq,
        "run_max_seq": max_seq,
    }
