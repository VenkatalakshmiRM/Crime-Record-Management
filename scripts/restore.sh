#!/usr/bin/env bash
set -euo pipefail

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

DB_NAME="${DB_NAME:-casework}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
MYSQL_LOGIN_PATH="${MYSQL_LOGIN_PATH:-casework}"
BACKUP_FILE="${1:-}"
CONFIRM="${2:-}"

if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
  echo "Usage: $0 <backup.sql> [--confirm]" >&2
  exit 2
fi
if ! command -v mysql >/dev/null 2>&1; then
  echo "ERROR: mysql client was not found. Install the MySQL client tools." >&2
  exit 1
fi
if [[ "$CONFIRM" != "--confirm" ]]; then
  echo "WARNING: a mysqldump restore can DROP and replace tables in database '$DB_NAME'." >&2
  read -r -p "Type RESTORE-$DB_NAME to continue: " answer
  if [[ "$answer" != "RESTORE-$DB_NAME" ]]; then
    echo "Restore cancelled." >&2
    exit 1
  fi
fi

mysql --login-path="$MYSQL_LOGIN_PATH" --host="$DB_HOST" --port="$DB_PORT" \
  "$DB_NAME" < "$BACKUP_FILE"
echo "Restore completed from: $BACKUP_FILE"
