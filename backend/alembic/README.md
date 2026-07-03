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

## Adopting an existing database (one-time)

If the database was created by the old `create_all` path, the tables already
exist. Baseline it once so Alembic does not try to recreate them:

    alembic stamp head

After stamping, use `alembic upgrade head` normally for all future changes.

## Notes

- The backend and the agent share one database but keep independent Alembic
  histories: the backend records its revisions in `backend_alembic_version`
  (see `alembic/env.py`), the agent uses the default `alembic_version`.
- `env.py` takes a Postgres advisory lock so the `backend` and `backend-celery`
  containers can start together without racing on migrations.
