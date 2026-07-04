# Backend database migrations (Alembic)

The backend schema is managed by Alembic. The container entrypoint runs
`alembic upgrade head` before starting the app, so migrations are applied
automatically on deploy. `Base.metadata.create_all` is no longer used.

Run commands from the `backend/` directory (needs `POSTGRES_DB_URL` set).

## Common workflows

Apply all migrations (fresh or existing, once adopted):

    alembic upgrade head

Create a new migration after changing models in `app/db/postgres/models/`:

    alembic revision --autogenerate -m "describe the change"
    # review the generated file in alembic/versions/, then:
    alembic upgrade head

Inspect state:

    alembic current
    alembic history

## Adopting an existing database

Handled automatically: the container entrypoint runs `python -m app.db.migrate`,
which detects a populated database with no version bookkeeping (the old
`create_all` path), stamps it with the **baseline revision** (`20260703_01`, not
`head` — so any migrations added later still apply), then upgrades normally.

To adopt manually instead (e.g. outside the container):

    alembic stamp 20260703_01
    alembic upgrade head

Only the API container runs migrations; Celery workers start with
`RUN_MIGRATIONS=false` (see podman-compose.yml). Concurrent runners are
serialized by the advisory lock in `env.py`.

## Notes

- The backend and the agent share one database but keep independent Alembic
  histories: the backend records its revisions in `backend_alembic_version`
  (see `alembic/env.py`), the agent uses the default `alembic_version`.
- `env.py` takes a Postgres advisory lock so the `backend` and `backend-celery`
  containers can start together without racing on migrations.
