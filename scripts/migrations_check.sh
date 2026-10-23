#!/usr/bin/env bash
# Проверка миграций: make migrations-check (этап «Миграции» в CI)
#
# В отдельной базе warehouse_migrations_check (рабочая и тестовая не
# затрагиваются; в конце база удаляется):
#   1. все миграции на чистой базе;
#   2. alembic check — модели в коде совпадают со схемой из миграций
#      (изменили модель и забыли миграцию — проверка падает);
#   3. история линейная: одна вершина;
#   4. откат до пустой базы — каждая миграция обратима;
#   5. повторное применение после отката.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
PG_USER="${POSTGRES_USER:-warehouse}"
PG_PASSWORD="${POSTGRES_PASSWORD:-warehouse}"
PG_PORT="${POSTGRES_PORT:-5432}"
CHECK_DB="warehouse_migrations_check"
CHECK_URL="postgresql+psycopg2://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/${CHECK_DB}"

if ! docker compose ps --status running -q db 2> /dev/null | grep -q .; then
    echo "База не запущена: выполните make dev-db" >&2
    exit 1
fi
[ -x .venv/bin/alembic ] || { echo "Нет .venv: выполните make setup" >&2; exit 1; }

alembic_check() { DATABASE_URL="$CHECK_URL" .venv/bin/alembic "$@"; }
drop_db() { docker compose exec -T db dropdb -U "$PG_USER" --if-exists "$CHECK_DB"; }

drop_db
docker compose exec -T db createdb -U "$PG_USER" "$CHECK_DB"
trap drop_db EXIT

echo "==> 1/5 все миграции на чистой базе"
alembic_check upgrade head
echo "==> 2/5 модели совпадают с миграциями (alembic check)"
alembic_check check
echo "==> 3/5 линейная история"
heads="$(alembic_check heads | grep -c '(head)' || true)"
[ "$heads" = "1" ] || { echo "Вершин истории: $heads (должна быть одна)" >&2; exit 1; }
alembic_check history | sed 's/^/    /'
echo "==> 4/5 откат всех миграций"
alembic_check downgrade base
echo "==> 5/5 повторное применение"
alembic_check upgrade head
alembic_check current
echo "Миграции применяются с нуля, обратимы и совпадают с моделями."
