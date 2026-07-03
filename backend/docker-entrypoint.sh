#!/bin/sh
set -eu

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

exec "$@"
