#!/usr/bin/env bash
# Start the MySQL container with plain `podman run`.
# podman-compose is not installed on this machine, so this is the reliable path.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME="${MYSQL_CONTAINER:-agentlog-mysql}"
PORT="${MYSQL_PORT:-3307}"
PASS="${MYSQL_ROOT_PASSWORD:-devroot}"
DB="${MYSQL_DATABASE:-agentlog}"
IMAGE="docker.io/library/mysql:8.4"

if podman container exists "$NAME"; then
  if [ "$(podman inspect -f '{{.State.Running}}' "$NAME")" = "true" ]; then
    echo "$NAME already running on port $PORT"
    exit 0
  fi
  echo "starting existing container $NAME"
  podman start "$NAME"
else
  echo "creating $NAME from $IMAGE on port $PORT"
  podman volume exists agentlog-data || podman volume create agentlog-data >/dev/null
  podman run -d \
    --name "$NAME" \
    -e MYSQL_ROOT_PASSWORD="$PASS" \
    -e MYSQL_DATABASE="$DB" \
    -p "${PORT}:3306" \
    -v "${ROOT}/infra/mysql/my.cnf:/etc/mysql/conf.d/zz-agentlog.cnf:ro,Z" \
    -v agentlog-data:/var/lib/mysql \
    "$IMAGE"
fi

printf 'waiting for mysql'
for _ in $(seq 1 90); do
  if podman exec "$NAME" mysqladmin ping -h 127.0.0.1 -uroot -p"$PASS" --silent >/dev/null 2>&1; then
    echo " ready on localhost:${PORT}"
    exit 0
  fi
  printf '.'
  sleep 2
done

echo
echo "mysql did not become ready in time; check: podman logs $NAME" >&2
exit 1
