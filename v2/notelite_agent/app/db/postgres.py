from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.engine import Engine

from app.core.config import POSTGRES_DB_URL


Base = declarative_base()


class DatabaseManager:
    _engine: Engine | None = None
    _session_factory: sessionmaker | None = None

    @classmethod
    def get_engine(cls) -> Engine:
        if cls._engine is None:
            cls._engine = create_engine(
                POSTGRES_DB_URL,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
            )

        return cls._engine

    @classmethod
    def get_session_factory(cls) -> sessionmaker:
        if cls._session_factory is None:
            cls._session_factory = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=cls.get_engine(),
            )

        return cls._session_factory

    @classmethod
    def get_session(cls):
        session = cls.get_session_factory()()

        try:
            yield session
        finally:
            session.close()

    @classmethod
    def dispose(cls):
        if cls._engine is not None:
            cls._engine.dispose()
            cls._engine = None
            cls._session_factory = None