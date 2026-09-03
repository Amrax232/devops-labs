#!/usr/bin/env bash
# Восстановление базы из резервной копии: make restore FILE=backups/<файл>.dump
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

FILE="${1:-}"
if [ -z "$FILE" ]; then
  echo "Укажите файл: make restore FILE=backups/warehouse-YYYYmmdd-HHMMSS.dump" >&2
  exit 1
fi
if [ ! -f "$FILE" ]; then
  echo "Файл не найден: $FILE" >&2
  exit 1
fi

PG_URL="${DATABASE_URL/+psycopg2/}"
pg_restore --clean --if-exists --no-owner --dbname="$PG_URL" "$FILE"
echo "База восстановлена из $FILE"
