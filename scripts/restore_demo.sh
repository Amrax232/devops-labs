#!/usr/bin/env bash
# Демонстрация восстановления после повреждения данных: make restore-demo
#
#   1. фиксируем состояние базы (число записей и суммарный остаток);
#   2. делаем резервную копию;
#   3. намеренно портим данные: удаляем строки поступлений и списания,
#      обнуляем остатки и переименовываем материалы;
#   4. восстанавливаем из копии;
#   5. сверяем состояние с исходным — оно должно совпасть полностью.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
PG_USER="${POSTGRES_USER:-warehouse}"
PG_DB="${POSTGRES_DB:-warehouse}"

sql() { docker compose exec -T db psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -tAc "$1"; }

snapshot() {
    sql "SELECT 'материалов: '     || (SELECT count(*) FROM materials)
             || ', строк поступлений: ' || (SELECT count(*) FROM receipt_items)
             || ', списаний: '      || (SELECT count(*) FROM write_offs)
             || ', остаток всего: ' || (SELECT coalesce(sum(quantity), 0) FROM materials)
             || ', контроль имён: ' || (SELECT md5(coalesce(string_agg(name, ',' ORDER BY id), ''))
                                        FROM materials)"
}

if ! docker compose ps --status running -q db 2>/dev/null | grep -q .; then
    echo "База не запущена: выполните make up" >&2
    exit 1
fi
if [ "$(sql 'SELECT count(*) FROM materials')" = "0" ]; then
    echo "В базе нет данных — сначала выполните make seed" >&2
    exit 1
fi

echo "==> 1/5 исходное состояние"
BEFORE="$(snapshot)"
echo "    $BEFORE"

echo "==> 2/5 резервная копия"
OUTPUT="$(./scripts/backup.sh)"
echo "    $OUTPUT"
FILE="$(echo "$OUTPUT" | sed -n 's/^Резервная копия сохранена: \([^ ]*\).*/\1/p')"

echo "==> 3/5 намеренное повреждение данных"
sql "BEGIN;
     DELETE FROM receipt_items;
     DELETE FROM write_offs;
     UPDATE materials SET quantity = 0, name = 'ИСПОРЧЕНО';
     COMMIT;" > /dev/null
DAMAGED="$(snapshot)"
echo "    $DAMAGED"

echo "==> 4/5 восстановление из $FILE"
./scripts/restore.sh "$FILE" | sed 's/^/    /'

echo "==> 5/5 сверка"
AFTER="$(snapshot)"
echo "    до:      $BEFORE"
echo "    после:   $AFTER"
if [ "$BEFORE" = "$AFTER" ]; then
    echo "Данные восстановлены полностью."
else
    echo "ОШИБКА: состояние после восстановления отличается от исходного" >&2
    exit 1
fi
