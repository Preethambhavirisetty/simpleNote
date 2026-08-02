"""Container-start migration runner: `python -m app.db.migrate`.

Applies Alembic migrations with a retry loop (Postgres may still be starting), and
adopts databases that predate Alembic: a schema created by the old
`Base.metadata.create_all` has the baseline tables but no version bookkeeping, so
`upgrade head` would fail on `CREATE TABLE users`. Such databases are stamped with
the baseline revision first, then upgraded normally.

Assumes a pre-Alembic database matches the baseline schema — true for any schema
created before migrations were introduced, since the baseline was generated from
those models. Concurrent runners are serialized by the advisory lock in
alembic/env.py; workers skip migrations entirely via RUN_MIGRATIONS=false.
"""
from __future__ import annotations

import os
import sys
import time

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import POSTGRES_DB_URL

# Must match the ids in alembic/: the baseline revision and env.py's version table.
BASELINE_REVISION = "20260703_01"
VERSION_TABLE = "backend_alembic_version"


def plan_migration(current_revision: str | None, has_users_table: bool) -> str:
    """Decide how to bring the database to head.

    - No version row + populated schema  -> pre-Alembic database: stamp baseline, upgrade.
    - No version row + empty database    -> fresh install: plain upgrade builds everything.
    - Version row present                -> normal case: plain upgrade.
    """
    if current_revision is None and has_users_table:
        return "stamp_then_upgrade"
    return "upgrade"


def _inspect_database() -> tuple[str | None, bool]:
    engine = create_engine(POSTGRES_DB_URL)
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            has_users_table = inspector.has_table("users")
            current_revision = None
            if inspector.has_table(VERSION_TABLE):
                current_revision = conn.execute(
                    text(f"SELECT version_num FROM {VERSION_TABLE}")  # noqa: S608 — constant table name
                ).scalar()
            return current_revision, has_users_table
    finally:
        engine.dispose()


def main() -> int:
    config = Config("alembic.ini")
    max_attempts = int(os.getenv("MIGRATION_MAX_ATTEMPTS", "30"))

    for attempt in range(1, max_attempts + 1):
        try:
            current_revision, has_users_table = _inspect_database()
            if plan_migration(current_revision, has_users_table) == "stamp_then_upgrade":
                print(
                    "Adopting pre-Alembic database: stamping baseline "
                    f"{BASELINE_REVISION} before upgrade.",
                    file=sys.stderr,
                )
                command.stamp(config, BASELINE_REVISION)
            command.upgrade(config, "head")
            return 0
        except Exception as exc:  # noqa: BLE001 — retry any startup-ordering failure
            if attempt >= max_attempts:
                print(f"Database migrations failed after {attempt} attempts: {exc}", file=sys.stderr)
                return 1
            print(
                f"Database migration attempt {attempt} failed ({type(exc).__name__}); "
                "retrying in 2 seconds.",
                file=sys.stderr,
            )
            time.sleep(2)
    return 1


if __name__ == "__main__":
    sys.exit(main())
