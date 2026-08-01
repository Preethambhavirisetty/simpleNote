"""Engine + small helpers for talking to MySQL with raw SQL.

No ORM: the queries here are shaped around specific indexes, and hiding them
behind a mapper would make it much harder to tell which index serves what.
"""

import json
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.core.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            pool_recycle=1800,
            future=True,
        )
    return _engine


def get_conn() -> Iterator[Connection]:
    """One connection per request. Reads need no explicit transaction; the
    connection is closed (rolling back the implicit read) when the request ends.

    Writers must wrap their work in ``with conn.begin():`` so the commit lands
    *inside* the handler. A ``yield`` dependency's cleanup runs only after the
    response has been sent, so committing there lets a client observe its own
    200 and then issue a follow-up request that cannot see the row it just
    created.
    """
    with get_engine().connect() as conn:
        yield conn


def q(sql: str) -> Any:
    return text(sql)


def as_json(value: Any) -> Any:
    """MySQL JSON columns come back from PyMySQL as strings; decode defensively."""
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def as_num(value: Any) -> float | int | None:
    """DECIMAL -> JSON-friendly number, keeping whole values as ints."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, default=str)
