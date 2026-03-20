"""
Shared fixtures and factory helpers for all test modules.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Generator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.postgres.session import get_postgres_session
from app.deps.auth import get_current_user
from app.exceptions.base import AppException
from app.main import app
from app.schema.base import ErrorCode


# ── Object factories ──────────────────────────────────────────────────────────

def make_user(**kwargs) -> SimpleNamespace:
    u = SimpleNamespace(
        id=uuid4(),
        name="Test User",
        email="test@example.com",
        hashed_password="hashed_secret",
        role=["standard_user"],
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    for k, v in kwargs.items():
        setattr(u, k, v)
    return u


def make_folder(**kwargs) -> SimpleNamespace:
    f = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        name="Work",
        is_pinned=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    for k, v in kwargs.items():
        setattr(f, k, v)
    return f


def make_note(**kwargs) -> SimpleNamespace:
    n = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        folder_id=None,
        title="My Note",
        content={"type": "doc", "content": []},
        content_text="",
        is_pinned=False,
        is_memory_included=False,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    for k, v in kwargs.items():
        setattr(n, k, v)
    return n


def make_tag(**kwargs) -> SimpleNamespace:
    t = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        name="python",
        created_at=datetime.now(timezone.utc),
    )
    for k, v in kwargs.items():
        setattr(t, k, v)
    return t


# ── Auth fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def current_user() -> SimpleNamespace:
    return make_user()


@pytest.fixture
def current_admin() -> SimpleNamespace:
    return make_user(role=["admin"], email="admin@example.com")


# ── DB fixture ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


# ── HTTP client helpers ───────────────────────────────────────────────────────

def _build_client(user: SimpleNamespace, mock_db: MagicMock) -> Generator:
    app.dependency_overrides[get_postgres_session] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: user
    with patch("app.main.init_postgres"), patch("app.main.dispose_postgres"):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client(current_user: SimpleNamespace, mock_db: MagicMock) -> Generator:
    yield from _build_client(current_user, mock_db)


@pytest.fixture
def admin_client(current_admin: SimpleNamespace, mock_db: MagicMock) -> Generator:
    yield from _build_client(current_admin, mock_db)


@pytest.fixture
def unauthed_client(mock_db: MagicMock) -> Generator:
    def _raise():
        raise AppException("Not authenticated", 401, ErrorCode.NOT_AUTHENTICATED)

    app.dependency_overrides[get_postgres_session] = lambda: mock_db
    app.dependency_overrides[get_current_user] = _raise
    with patch("app.main.init_postgres"), patch("app.main.dispose_postgres"):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()
