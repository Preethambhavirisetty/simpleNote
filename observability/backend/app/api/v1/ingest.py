"""Write path. This is what your agent POSTs to."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import bindparam
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.core.db import dumps, get_conn, q
from app.schemas.ingest import LogBatch, RunFinish, RunStart
from app.services.field_router import insert_fields, register_fields, route_value

router = APIRouter(tags=["ingest"])

# `IN :seqs` against a Python list needs an expanding bindparam
_SEQS_EXISTING = q("SELECT seq FROM logs WHERE run_id = :r AND seq IN :seqs").bindparams(
    bindparam("seqs", expanding=True)
)
_SEQ_TO_ID = q("SELECT seq, id FROM logs WHERE run_id = :r AND seq IN :seqs").bindparams(
    bindparam("seqs", expanding=True)
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(value: datetime | None) -> datetime:
    """Store UTC-naive: the column is DATETIME(6) and the server runs at +00:00."""
    if value is None:
        return _now()
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _run_id(conn: Connection, run_key: str) -> int:
    row = conn.execute(
        q("SELECT id FROM runs WHERE run_key = :k"), {"k": run_key}
    ).first()
    if row is None:
        raise HTTPException(404, f"unknown run_key {run_key!r}")
    return int(row[0])


@router.post("/runs")
def start_run(body: RunStart, conn: Connection = Depends(get_conn)) -> dict:
    """Create or update a run. Safe to call twice with the same run_key."""
    with conn.begin():
        conn.execute(
            q(
                """
                INSERT INTO runs
                  (run_key, conversation_id, question, started_at, metadata_json)
                VALUES
                  (:run_key, :conversation_id, :question, :started_at,
                   CAST(:metadata AS JSON))
                ON DUPLICATE KEY UPDATE
                  conversation_id = COALESCE(VALUES(conversation_id), conversation_id),
                  question        = COALESCE(VALUES(question), question),
                  metadata_json   = COALESCE(VALUES(metadata_json), metadata_json)
                """
            ),
            {
                "run_key": body.run_key,
                "conversation_id": body.conversation_id,
                "question": body.question,
                "started_at": _naive(body.started_at),
                "metadata": dumps(body.metadata),
            },
        )
        run_id = _run_id(conn, body.run_key)
    return {"run_key": body.run_key, "id": run_id}


@router.post("/runs/{run_key}/logs")
def append_logs(
    run_key: str, body: LogBatch, conn: Connection = Depends(get_conn)
) -> dict:
    """Append a batch of log lines, plus any tracked fields they carry."""
    limit = get_settings().log_batch_max
    if len(body.logs) > limit:
        raise HTTPException(413, f"batch too large: {len(body.logs)} > {limit}")
    if not body.logs:
        return {"accepted": 0, "duplicates": 0, "tracked": 0}

    with conn.begin():
        run_id = _run_id(conn, run_key)
        seqs = [line.seq for line in body.logs]
        if len(set(seqs)) != len(seqs):
            raise HTTPException(422, "duplicate seq values within the same batch")

        # count pre-existing seqs so the response can report duplicates honestly
        existing = {
            int(r[0])
            for r in conn.execute(_SEQS_EXISTING, {"r": run_id, "seqs": seqs})
        }

        conn.execute(
            q(
                """
                INSERT INTO logs
                  (run_id, seq, ts, level, phase, message, source, data_json, duration_ms)
                VALUES
                  (:run_id, :seq, :ts, :level, :phase, :message, :source,
                   CAST(:data AS JSON), :duration_ms)
                ON DUPLICATE KEY UPDATE
                  ts = VALUES(ts), level = VALUES(level), phase = VALUES(phase),
                  message = VALUES(message), source = VALUES(source),
                  data_json = VALUES(data_json), duration_ms = VALUES(duration_ms)
                """
            ),
            [
                {
                    "run_id": run_id,
                    "seq": line.seq,
                    "ts": _naive(line.ts),
                    "level": line.level,
                    "phase": line.phase,
                    "message": line.message,
                    "source": line.source,
                    "data": dumps(line.data),
                    "duration_ms": line.duration_ms,
                }
                for line in body.logs
            ],
        )

        # map seq -> log id so tracked fields can point back at their emitting line
        log_ids = {
            int(r[0]): int(r[1])
            for r in conn.execute(_SEQ_TO_ID, {"r": run_id, "seqs": seqs})
        }

        routed, rows = [], []
        for line in body.logs:
            for name, value in (line.track or {}).items():
                item = route_value(name, value)
                routed.append(item)
                rows.append(
                    {
                        **item,
                        "run_id": run_id,
                        "log_id": log_ids.get(line.seq),
                        "seq": line.seq,
                        "ts": _naive(line.ts),
                    }
                )
        if routed:
            register_fields(conn, routed)
            insert_fields(conn, rows)

        _recount(conn, run_id)
    return {
        "accepted": len(body.logs),
        "duplicates": len(existing),
        "tracked": len(rows),
    }


@router.post("/runs/{run_key}/finish")
def finish_run(
    run_key: str, body: RunFinish, conn: Connection = Depends(get_conn)
) -> dict:
    with conn.begin():
        run_id = _run_id(conn, run_key)
        conn.execute(
            q(
                """
                UPDATE runs
                   SET status        = :status,
                       final_answer  = COALESCE(:final_answer, final_answer),
                       error_message = COALESCE(:error_message, error_message),
                       ended_at      = :ended_at,
                       duration_ms   = GREATEST(
                           0, TIMESTAMPDIFF(MICROSECOND, started_at, :ended_at) DIV 1000)
                 WHERE id = :id
                """
            ),
            {
                "status": body.status,
                "final_answer": body.final_answer,
                "error_message": body.error_message,
                "ended_at": _naive(body.ended_at),
                "id": run_id,
            },
        )
        _recount(conn, run_id)
    return {"run_key": run_key, "status": body.status}


def _recount(conn: Connection, run_id: int) -> None:
    """Recompute the run's denormalised counters.

    Cheap enough to redo on every batch, and being derived rather than
    incremented means a replayed batch can never double-count.
    """
    conn.execute(
        q(
            """
            UPDATE runs r
               SET log_count   = (SELECT COUNT(*) FROM logs l WHERE l.run_id = r.id),
                   error_count = (SELECT COUNT(*) FROM logs l
                                   WHERE l.run_id = r.id AND l.level = 'ERROR'),
                   max_seq     = COALESCE(
                       (SELECT MAX(seq) FROM logs l WHERE l.run_id = r.id), 0)
             WHERE r.id = :id
            """
        ),
        {"id": run_id},
    )
