#!/bin/bash
# Wait for PostgreSQL to be ready

set -e

host="simplenote-db"
port="5432"
max_attempts=30
attempt=0

echo "Waiting for PostgreSQL at $host:$port..."

until pg_isready -h "$host" -p "$port" -U simplenote_user > /dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ $attempt -ge $max_attempts ]; then
    echo "PostgreSQL did not become ready in time"
    exit 1
  fi
  echo "PostgreSQL is unavailable - attempt $attempt/$max_attempts"
  sleep 2
done

echo "PostgreSQL is ready!"

# Execute the command passed to the script
exec "$@"

