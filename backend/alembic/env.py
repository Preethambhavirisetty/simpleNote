from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.core.config import POSTGRES_DB_URL
import app.db.postgres.models  # noqa: F401 — registers all models with Base
from app.db.postgres.base import Base


config = context.config
config.set_main_option("sqlalchemy.url", POSTGRES_DB_URL)
target_metadata = Base.metadata

# The backend and the agent migrate the same database with independent histories.
# Keep the backend's revision bookkeeping in its own table so the two never collide.
VERSION_TABLE = "backend_alembic_version"

# Distinct from the agent's advisory lock so backend instances only serialize with
# each other (backend + backend-celery start together).
MIGRATION_LOCK_ID = 731946285


def run_migrations_offline() -> None:
    context.configure(
        url=POSTGRES_DB_URL,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_ID})"))
        connection.commit()
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table=VERSION_TABLE,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_ID})"))
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
