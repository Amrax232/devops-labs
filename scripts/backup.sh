#!/usr/bin/env bash
# Резервная копия базы данных: make backup
#
# - формат custom (pg_dump -Fc): сжатый архив, восстанавливается pg_restore;
# - копия пишется во временный файл и переименовывается только после успеха,
#   поэтому оборванный дамп никогда не выглядит как готовая копия;
# - архив сразу проверяется чтением оглавления (pg_restore --list);
# - рядом сохраняется контрольная сумма SHA-256 — restore откажется
#   восстанавливать повреждённый файл;
# - хранится BACKUP_KEEP последних копий, более старые удаляются.
#
# База в docker compose → pg_dump из контейнера (версия клиента совпадает с
# сервером). Иначе — локальный pg_dump по DATABASE_URL (например, на сервере ЛР2).
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

BACKUP_DIR="${BACKUP_DIR:-backups}"
BACKUP_KEEP="${BACKUP_KEEP:-10}"
PREFIX="${BACKUP_PREFIX:-warehouse}"
PG_USER="${POSTGRES_USER:-warehouse}"
PG_DB="${POSTGRES_DB:-warehouse}"

use_docker() { docker compose ps --status running -q db 2>/dev/null | grep -q .; }

mkdir -p "$BACKUP_DIR"
FILE="$BACKUP_DIR/$PREFIX-$(date +%Y%m%d-%H%M%S).dump"
PARTIAL="$FILE.partial"
trap 'rm -f "$PARTIAL"' EXIT

if use_docker; then
    docker compose exec -T db pg_dump -U "$PG_USER" -d "$PG_DB" \
        --format=custom --no-owner > "$PARTIAL"
    docker compose exec -T db pg_restore --list < "$PARTIAL" > /dev/null
else
    PG_URL="${DATABASE_URL/+psycopg2/}"
    pg_dump --format=custom --no-owner --dbname="$PG_URL" --file="$PARTIAL"
    pg_restore --list "$PARTIAL" > /dev/null
fi

mv "$PARTIAL" "$FILE"
sha256sum "$FILE" > "$FILE.sha256"

# ротация: оставляем BACKUP_KEEP последних копий с этим префиксом
ls -1t "$BACKUP_DIR/$PREFIX"-*.dump 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" |
    while read -r old; do rm -f "$old" "$old.sha256"; done

echo "Резервная копия сохранена: $FILE ($(du -h "$FILE" | cut -f1))"
