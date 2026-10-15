#!/usr/bin/env bash
# Восстановление базы из резервной копии: make restore FILE=backups/<файл>.dump
#
# Порядок:
#   1) проверка контрольной суммы — повреждённый архив не восстанавливается;
#   2) страховочная копия текущего состояния (префикс pre-restore) — если
#      восстановили не тот файл, можно вернуться обратно;
#   3) pg_restore --clean --single-transaction: объекты пересоздаются, а вся
#      операция выполняется одной транзакцией — при ошибке база остаётся
#      в исходном состоянии, а не «наполовину восстановленной».
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

FILE="${1:-}"
PG_USER="${POSTGRES_USER:-warehouse}"
PG_DB="${POSTGRES_DB:-warehouse}"

if [ -z "$FILE" ]; then
    echo "Укажите файл: make restore FILE=backups/warehouse-YYYYmmdd-HHMMSS.dump" >&2
    ls -1t backups/*.dump 2>/dev/null | head -5 | sed 's/^/  доступно: /' >&2 || true
    exit 1
fi
if [ ! -f "$FILE" ]; then
    echo "Файл не найден: $FILE" >&2
    exit 1
fi

echo "==> 1/3 проверка архива"
if [ -f "$FILE.sha256" ]; then
    sha256sum --quiet -c "$FILE.sha256" || { echo "Контрольная сумма не совпадает" >&2; exit 1; }
    echo "    контрольная сумма совпадает"
else
    echo "    файла $FILE.sha256 нет — контрольная сумма не проверена"
fi

use_docker() { docker compose ps --status running -q db 2>/dev/null | grep -q .; }

echo "==> 2/3 страховочная копия текущего состояния"
BACKUP_PREFIX=pre-restore ./scripts/backup.sh | sed 's/^/    /'

echo "==> 3/3 восстановление"
if use_docker; then
    docker compose exec -T db pg_restore -U "$PG_USER" -d "$PG_DB" \
        --clean --if-exists --no-owner --single-transaction < "$FILE"
else
    PG_URL="${DATABASE_URL/+psycopg2/}"
    pg_restore --clean --if-exists --no-owner --single-transaction --dbname="$PG_URL" "$FILE"
fi
echo "База восстановлена из $FILE"
