#!/bin/sh
set -eu

# Exactly one process should migrate the database. Compose sets
# RUN_MIGRATIONS=false on the Celery worker so only the agent API container runs
# this; concurrent runners are serialized by the advisory lock in alembic/env.py.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    max_attempts="${MIGRATION_MAX_ATTEMPTS:-30}"
    attempt=1

    while ! alembic upgrade head; do
        if [ "$attempt" -ge "$max_attempts" ]; then
            echo "Database migrations failed after $attempt attempts." >&2
            exit 1
        fi
        echo "Database migration attempt $attempt failed; retrying in 2 seconds." >&2
        attempt=$((attempt + 1))
        sleep 2
    done
else
    echo "RUN_MIGRATIONS=false - skipping database migrations." >&2
fi

exec "$@"
