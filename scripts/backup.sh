#!/usr/bin/env bash
# Резервная копия базы данных. Запускается через `make backup`.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

BACKUP_DIR="${BACKUP_DIR:-backups}"
mkdir -p "$BACKUP_DIR"

# pg_dump понимает обычный URL, поэтому убираем драйвер SQLAlchemy (+psycopg2)
PG_URL="${DATABASE_URL/+psycopg2/}"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="$BACKUP_DIR/warehouse-$STAMP.dump"

pg_dump --format=custom --no-owner --dbname="$PG_URL" --file="$FILE"
echo "Резервная копия сохранена: $FILE"
