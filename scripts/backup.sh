#!/usr/bin/env bash
set -euo pipefail

# Optional .env loading: values must be shell-compatible KEY=value assignments.
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
OUT_FILE="${1:-casework-$(date -u +%Y%m%dT%H%M%SZ).sql}"

if ! command -v mysqldump >/dev/null 2>&1; then
  echo "ERROR: mysqldump was not found. Install the MySQL client tools." >&2
  exit 1
fi
if [[ -e "$OUT_FILE" ]]; then
  echo "ERROR: refusing to overwrite existing backup: $OUT_FILE" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT_FILE")"
PART_FILE="${OUT_FILE}.part.$$"
trap 'rm -f "$PART_FILE"' EXIT
mysqldump --login-path="$MYSQL_LOGIN_PATH" --host="$DB_HOST" --port="$DB_PORT" \
  --single-transaction --routines --triggers --events --hex-blob --set-gtid-purged=OFF \
  "$DB_NAME" > "$PART_FILE"
chmod 600 "$PART_FILE"
mv -- "$PART_FILE" "$OUT_FILE"
trap - EXIT
echo "Backup created: $OUT_FILE"
