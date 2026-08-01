"""Test fixtures.

Integration tests run against a real MySQL (the same container, a separate
`agentlog_test` database) rather than a stub. The behaviour worth testing here
-- ON DUPLICATE KEY idempotency, DECIMAL routing, correlated EXISTS filters --
is behaviour of MySQL itself, so a fake would prove nothing.
"""

import os
import pathlib

import pytest

TEST_DB = os.environ.setdefault("MYSQL_DATABASE", "agentlog_test")
os.environ.setdefault("MYSQL_PORT", "3307")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import get_engine  # noqa: E402
from app.main import app  # noqa: E402

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "db" / "migrations"


@pytest.fixture(scope="session", autouse=True)
def database():
    s = get_settings()
    root_url = (
        f"mysql+pymysql://{s.mysql_user}:{s.mysql_password}"
        f"@{s.mysql_host}:{s.mysql_port}/?charset=utf8mb4"
    )
    admin = create_engine(root_url, future=True)
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{s.mysql_database}`"))
        conn.execute(
            text(
                f"CREATE DATABASE `{s.mysql_database}` "
                "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
            )
        )
        conn.commit()

    with get_engine().begin() as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(text(path.read_text()))

    yield

    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{s.mysql_database}`"))
        conn.commit()
    admin.dispose()


@pytest.fixture(autouse=True)
def clean_tables(database):
    """Each test starts from an empty database."""
    with get_engine().begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in ("tracked_fields", "logs", "runs", "field_defs"):
            conn.execute(text(f"TRUNCATE TABLE {table}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_run(client):
    """Create a run and append one batch of lines; returns the run_key."""

    def _make(run_key="r1", question="why is checkout-api 503ing", logs=None, **kw):
        client.post(
            "/api/v1/runs",
            json={"run_key": run_key, "question": question, **kw},
        ).raise_for_status()
        if logs:
            client.post(
                f"/api/v1/runs/{run_key}/logs", json={"logs": logs}
            ).raise_for_status()
        return run_key

    return _make
