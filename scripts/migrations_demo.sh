#!/usr/bin/env bash
# Миграции на чистой и на заполненной базе: make migrations-demo
#
# Всё выполняется в отдельной базе warehouse_migrations_demo, рабочая база
# не затрагивается. В конце демонстрационная база удаляется.
# Alembic запускается в контейнерной среде — разовым контейнером migrate
# (тот же образ, что и у приложения), база — сервис db во внутренней сети.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
PG_USER="${POSTGRES_USER:-warehouse}"
PG_PASSWORD="${POSTGRES_PASSWORD:-warehouse}"
DEMO_DB="warehouse_migrations_demo"
DEMO_URL="postgresql+psycopg2://${PG_USER}:${PG_PASSWORD}@db:5432/${DEMO_DB}"

psql_demo() { docker compose exec -T db psql -U "$PG_USER" -d "$DEMO_DB" -v ON_ERROR_STOP=1 "$@"; }
alembic_demo() {
    docker compose run --rm --no-deps -T -e DATABASE_URL="$DEMO_URL" migrate alembic "$@"
}

if ! docker compose ps --status running -q db 2> /dev/null | grep -q .; then
    echo "База не запущена: выполните make up" >&2
    exit 1
fi

docker compose exec -T db dropdb -U "$PG_USER" --if-exists "$DEMO_DB"
docker compose exec -T db createdb -U "$PG_USER" "$DEMO_DB"
trap 'docker compose exec -T db dropdb -U "$PG_USER" --if-exists "$DEMO_DB"' EXIT

echo "==> 1/3 чистая база: все миграции с нуля"
alembic_demo upgrade head
alembic_demo current
psql_demo -c '\dt'

echo "==> 2/3 откат к версии 0002 и заполнение данными «старой» схемы"
alembic_demo downgrade 0002
psql_demo -c "INSERT INTO units (code, name) VALUES ('pcs', 'Штука');
              INSERT INTO materials (sku, name, unit_id, quantity, min_stock)
                     VALUES ('MAT-001', 'Болт М8х40', 1, 125.5, 10),
                            ('MAT-002', 'Гайка М8', 1, 300, 50);"
psql_demo -c "SELECT id, sku, name, quantity FROM materials ORDER BY id;"

echo "==> 3/3 обновление заполненной базы до последней версии"
alembic_demo upgrade head
alembic_demo current
psql_demo -c "SELECT id, sku, name, quantity, location FROM materials ORDER BY id;"
echo "Данные сохранились, новая колонка location заполнена значением по умолчанию."
