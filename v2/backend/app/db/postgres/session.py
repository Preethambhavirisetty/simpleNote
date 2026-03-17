from collections.abc import Generator
from sqlalchemy import create_engine, Engine, text
from sqlalchemy.orm import Session, sessionmaker

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_postgres(db_url: str) -> None:
    """Create engine, session factory, and tables. Called once at app startup."""
    global engine, SessionLocal
    from app.db.postgres.base import Base
    # import app.db.postgres.models.user  # noqa: F401 — registers User model with Base
    import app.db.postgres.models

    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        future=True
    )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)

    # Verify connection is reachable at startup
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    # Create all tables that don't exist yet (safe to run repeatedly)
    Base.metadata.create_all(engine)


def dispose_postgres() -> None:
    """Dispose engine pool. Called on app shutdown."""
    global engine
    if engine:
        engine.dispose()
        engine = None


def get_postgres_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a Postgres session."""
    if SessionLocal is None:
        raise RuntimeError("Postgres is not initialised. POSTGRES_DB_URL may not be set.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
