#!/bin/sh
set -eu

# Exactly one process should migrate the database. Compose sets
# RUN_MIGRATIONS=false on Celery workers so only the API container runs this;
# concurrent API replicas are serialized by the advisory lock in alembic/env.py.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    python -m app.db.migrate
else
    echo "RUN_MIGRATIONS=false - skipping database migrations." >&2
fi

exec "$@"
