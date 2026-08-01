"""The tracked-field registry."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Connection

from app.core.db import get_conn, iso, q
from app.schemas.ingest import FieldDefPatch

router = APIRouter(tags=["fields"])


@router.get("/fields")
def list_fields(
    conn: Connection = Depends(get_conn), pinned_only: bool = False
) -> dict:
    where = "WHERE pinned = 1" if pinned_only else ""
    rows = conn.execute(
        q(
            f"""SELECT name, label, kind, unit, pinned, display_order, aggregate,
                       first_seen_at, last_seen_at, use_count
                  FROM field_defs {where}
              ORDER BY pinned DESC, display_order, name"""
        )
    ).mappings().all()
    return {
        "items": [
            {
                "name": r["name"],
                "label": r["label"] or r["name"].replace("_", " "),
                "kind": r["kind"],
                "unit": r["unit"],
                "pinned": bool(r["pinned"]),
                "display_order": r["display_order"],
                "aggregate": r["aggregate"],
                "first_seen_at": iso(r["first_seen_at"]),
                "last_seen_at": iso(r["last_seen_at"]),
                "use_count": int(r["use_count"]),
            }
            for r in rows
        ]
    }


@router.patch("/fields/{name}")
def patch_field(
    name: str, body: FieldDefPatch, conn: Connection = Depends(get_conn)
) -> dict:
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "nothing to update")

    sets = ", ".join(f"{col} = :{col}" for col in updates)
    with conn.begin():
        result = conn.execute(
            q(f"UPDATE field_defs SET {sets} WHERE name = :name"),
            {**updates, "name": name},
        )
        if result.rowcount == 0:
            # rowcount is also 0 when the update is a no-op, so distinguish
            # "unknown field" from "already had these values"
            exists = conn.execute(
                q("SELECT 1 FROM field_defs WHERE name = :name"), {"name": name}
            ).first()
            if exists is None:
                raise HTTPException(404, f"unknown field {name!r}")
    return {"name": name, **updates}
