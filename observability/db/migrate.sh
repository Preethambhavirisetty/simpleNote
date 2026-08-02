#!/usr/bin/env bash
# Apply db/migrations/*.sql in order, recording each in schema_migrations.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${MYSQL_CONTAINER:-agentlog-mysql}"
PASS="${MYSQL_ROOT_PASSWORD:-devroot}"
DB="${MYSQL_DATABASE:-agentlog}"

mysql_run() { podman exec -i "$NAME" mysql -uroot -p"$PASS" --default-character-set=utf8mb4 "$@"; }

mysql_run -e "CREATE DATABASE IF NOT EXISTS \`$DB\`
                DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci;"

mysql_run "$DB" -e "CREATE TABLE IF NOT EXISTS schema_migrations (
  filename   VARCHAR(191) NOT NULL,
  applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (filename)
) ENGINE=InnoDB;"

applied=0
for f in "$ROOT"/db/migrations/*.sql; do
  base="$(basename "$f")"
  seen="$(mysql_run -N -B "$DB" -e \
    "SELECT COUNT(*) FROM schema_migrations WHERE filename='$base';")"
  if [ "$seen" != "0" ]; then
    echo "  skip  $base"
    continue
  fi
  echo "  apply $base"
  mysql_run "$DB" < "$f"
  mysql_run "$DB" -e "INSERT INTO schema_migrations (filename) VALUES ('$base');"
  applied=$((applied + 1))
done

echo "migrations complete ($applied applied)"
mysql_run -N -B "$DB" -e "SHOW TABLES;" | sed 's/^/  table: /'
