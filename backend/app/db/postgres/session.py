from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_postgres(db_url: str) -> None:
    """Create the engine and session factory. Called once at app startup.

    The schema itself is managed by Alembic migrations (`alembic upgrade head`,
    run by the container entrypoint), not by this function.
    """
    global engine, SessionLocal

    engine = create_engine(
        db_url,
        # Each request holds one connection for its lifetime.
        # pool_size = steady-state concurrent requests the pool serves without overflow.
        # max_overflow = burst headroom on top of pool_size.
        # pool_timeout = seconds to wait for a free connection before raising TimeoutError.
        # pool_recycle = close connections idle longer than this (seconds) to avoid
        #                server-side "connection reset" errors on long-lived pools.
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_timeout=10,
        pool_recycle=1800,
        future=True,
    )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)

    # Verify connection is reachable at startup
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def dispose_postgres() -> None:
    """Dispose engine pool. Called on app shutdown."""
    global engine
    if engine:
        engine.dispose()
        engine = None


def get_postgres_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a scoped Postgres session.

    Lifecycle:
    - yield   → route handler runs
    - except  → explicit rollback so the connection is returned cleanly to the pool
    - finally → session closed and connection released back to the pool regardless
    """
    if SessionLocal is None:
        raise RuntimeError("Postgres is not initialised. POSTGRES_DB_URL may not be set.")
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_standalone_session() -> Generator[Session, None, None]:
    """Context-manager session for use outside the request lifecycle (e.g. Celery tasks).

    Lazily initialises the Postgres connection if the worker hasn't called init_postgres yet.
    """
    if SessionLocal is None:
        from app.core.config import POSTGRES_DB_URL  # avoid circular import at module level

        init_postgres(POSTGRES_DB_URL)
    db = SessionLocal()  # type: ignore[misc]
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
