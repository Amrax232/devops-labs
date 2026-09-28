#!/usr/bin/env bash
# Сервер базы данных: установка PostgreSQL, база и пользователь приложения.
#
# Запуск (от root на машине warehouse-db):
#   DB_PASSWORD='<пароль>' bash 10-install-postgres.sh
#
# Пароль НЕ хранится в репозитории: он передаётся переменной окружения и
# попадает только в /etc/warehouse/warehouse.env на сервере приложения.
set -euo pipefail

APP_IP="${APP_IP:-192.168.56.10}"
DB_IP="${DB_IP:-192.168.56.11}"
DB_NAME="${DB_NAME:-warehouse}"
DB_USER="${DB_USER:-warehouse}"
DB_PASSWORD="${DB_PASSWORD:-}"

if [[ $EUID -ne 0 ]]; then
    echo "Скрипт нужно запускать от root" >&2
    exit 1
fi
if [[ -z "$DB_PASSWORD" ]]; then
    echo "Задайте пароль: DB_PASSWORD='...' bash $0" >&2
    echo "Сгенерировать: openssl rand -base64 24" >&2
    exit 1
fi

echo "==> 1/4 установка PostgreSQL"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq postgresql postgresql-client

PG_VERSION="$(psql --version | grep -oE '[0-9]+' | head -1)"
PG_CONF_DIR="/etc/postgresql/${PG_VERSION}/main"
echo "    найден PostgreSQL ${PG_VERSION}, конфигурация: ${PG_CONF_DIR}"

echo "==> 2/4 база данных и пользователь с минимальными правами"
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
    ELSE
        ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
    END IF;
END
\$\$;

-- Роль приложения обычная: без SUPERUSER, CREATEDB и CREATEROLE.
ALTER ROLE ${DB_USER} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
SQL

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1; then
    sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"
    echo "    база ${DB_NAME} создана"
fi

# Подключаться к базе может только её владелец, а не все подряд.
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<SQL
REVOKE ALL ON DATABASE ${DB_NAME} FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

echo "==> 3/4 сетевой доступ: слушаем только внутреннюю сеть"
# Снаружи (из NAT-интерфейса) PostgreSQL недоступен в принципе.
sed -i "s/^#\?listen_addresses.*/listen_addresses = 'localhost,${DB_IP}'/" \
    "${PG_CONF_DIR}/postgresql.conf"

HBA_LINE="host    ${DB_NAME}    ${DB_USER}    ${APP_IP}/32    scram-sha-256"
if ! grep -qF "${HBA_LINE}" "${PG_CONF_DIR}/pg_hba.conf"; then
    printf '\n# Приложение подключается только с сервера warehouse-app\n%s\n' \
        "${HBA_LINE}" >> "${PG_CONF_DIR}/pg_hba.conf"
fi

systemctl enable --now postgresql
systemctl restart postgresql

echo "==> 4/4 проверка"
sudo -u postgres psql -tAc "SELECT rolname, rolsuper, rolcreatedb FROM pg_roles WHERE rolname='${DB_USER}'"
ss -ltnp | grep 5432 || true

cat <<MSG

База данных готова. Строка подключения для сервера приложения:
  postgresql+psycopg2://${DB_USER}:<пароль>@${DB_IP}:5432/${DB_NAME}

Дальше выполните 20-firewall-db.sh, чтобы закрыть порт 5432 для всех,
кроме ${APP_IP}.
MSG
