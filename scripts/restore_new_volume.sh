#!/usr/bin/env bash
# Восстановление резервной копии в НОВЫЙ том: make restore-new-volume [FILE=...]
#
# Проверяет главное свойство резервной копии — из неё можно поднять базу «с нуля»
# на пустом томе, а не только откатить существующую:
#   1. фиксирует состояние рабочей базы и делает копию (если FILE не указан);
#   2. поднимает отдельный экземпляр PostgreSQL в отдельном проекте compose
#      (${CHECK_PROJECT}) — со своим новым пустым томом и своей сетью;
#   3. восстанавливает копию в него одной транзакцией;
#   4. сверяет данные и версию схемы с рабочей базой.
# Рабочий том и рабочие контейнеры не затрагиваются. В конце проверочный
# проект удаляется вместе с томом; KEEP_RESTORED=1 — оставить для демонстрации.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

FILE="${1:-}"
PG_USER="${POSTGRES_USER:-warehouse}"
PG_DB="${POSTGRES_DB:-warehouse}"
CHECK_PROJECT="${CHECK_PROJECT:-warehouse-restore-check}"

main_sql() { docker compose exec -T db psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -tAc "$1"; }
new_compose() { docker compose -p "$CHECK_PROJECT" "$@"; }
new_sql() { new_compose exec -T db psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -tAc "$1"; }

SNAPSHOT_SQL="SELECT 'единиц: '        || (SELECT count(*) FROM units)
                  || ', поставщиков: '  || (SELECT count(*) FROM suppliers)
                  || ', материалов: '   || (SELECT count(*) FROM materials)
                  || ', поступлений: '  || (SELECT count(*) FROM receipts)
                  || ', списаний: '     || (SELECT count(*) FROM write_offs)
                  || ', остаток: '      || (SELECT coalesce(sum(quantity), 0) FROM materials)
                  || ', схема: '        || (SELECT string_agg(version_num, ',') FROM alembic_version)
                  || ', контроль: '     || (SELECT md5(coalesce(string_agg(sku || name || quantity, ','
                                                    ORDER BY id), '')) FROM materials)"

cleanup() {
    if [ "${KEEP_RESTORED:-0}" = "1" ]; then
        echo "Проверочная база оставлена: docker compose -p $CHECK_PROJECT exec db psql -U $PG_USER $PG_DB"
        echo "Удалить: docker compose -p $CHECK_PROJECT down -v"
    else
        new_compose down -v --remove-orphans > /dev/null 2>&1 || true
    fi
}

if ! docker compose ps --status running -q db 2> /dev/null | grep -q .; then
    echo "Рабочая база не запущена: выполните make up" >&2
    exit 1
fi

echo "==> 1/4 рабочая база и резервная копия"
BEFORE="$(main_sql "$SNAPSHOT_SQL")"
echo "    рабочая база: $BEFORE"
if [ -z "$FILE" ]; then
    OUTPUT="$(./scripts/backup.sh)"
    echo "    $OUTPUT"
    FILE="$(echo "$OUTPUT" | sed -n 's/^Резервная копия сохранена: \([^ ]*\).*/\1/p')"
fi
[ -f "$FILE" ] || { echo "Файл не найден: $FILE" >&2; exit 1; }
if [ -f "$FILE.sha256" ]; then
    sha256sum --quiet -c "$FILE.sha256" || { echo "Контрольная сумма не совпадает" >&2; exit 1; }
    echo "    контрольная сумма $FILE совпадает"
fi

echo "==> 2/4 новый пустой том и отдельный экземпляр PostgreSQL"
trap cleanup EXIT
new_compose down -v --remove-orphans > /dev/null 2>&1 || true
new_compose up -d db > /dev/null 2>&1
for _ in $(seq 1 60); do
    # по TCP: временный сервер initdb слушает только сокет
    new_compose exec -T db pg_isready -q -h 127.0.0.1 -U "$PG_USER" -d "$PG_DB" 2> /dev/null && break
    sleep 1
done
new_compose exec -T db pg_isready -q -h 127.0.0.1 -U "$PG_USER" -d "$PG_DB" \
    || { echo "Проверочный PostgreSQL не запустился" >&2; exit 1; }
VOLUME="${CHECK_PROJECT}_db_data"
echo "    том: $VOLUME (создан $(docker volume inspect -f '{{.CreatedAt}}' "$VOLUME"))"
echo "    таблиц в новой базе до восстановления: $(new_sql \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"

echo "==> 3/4 восстановление из $FILE"
new_compose exec -T db pg_restore -U "$PG_USER" -d "$PG_DB" \
    --no-owner --exit-on-error --single-transaction < "$FILE"
echo "    восстановлено"

echo "==> 4/4 сверка"
AFTER="$(new_sql "$SNAPSHOT_SQL")"
echo "    рабочая база:        $BEFORE"
echo "    восстановленная:     $AFTER"
if [ "$BEFORE" != "$AFTER" ]; then
    echo "ОШИБКА: данные восстановленной базы отличаются" >&2
    exit 1
fi
echo "Копия восстановлена в новый том, данные совпадают. Рабочий том не изменялся."
