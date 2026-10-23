#!/usr/bin/env bash
# Сервер приложения: среда выполнения, служебный пользователь и каталоги.
#
# Запуск (от root на машине app):  bash 10-install-runtime.sh
set -euo pipefail

APP_USER="${APP_USER:-warehouse}"
APP_HOME="${APP_HOME:-/opt/warehouse}"
CONFIG_DIR="${CONFIG_DIR:-/etc/warehouse}"

if [[ $EUID -ne 0 ]]; then
    echo "Скрипт нужно запускать от root" >&2
    exit 1
fi

echo "==> 1/4 пакеты среды выполнения"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-dev build-essential \
    libpq-dev postgresql-client git curl

echo "==> 2/4 системный пользователь ${APP_USER}"
# Служебная учётная запись: без пароля, без домашнего каталога и без оболочки —
# под ней нельзя войти в систему, она нужна только для запуска сервиса.
if ! id "$APP_USER" >/dev/null 2>&1; then
    adduser --system --group --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> 3/4 каталоги и права"
# Код принадлежит приложению, посторонние прочитать его не могут (750).
install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$APP_HOME"
install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$APP_HOME/current"
# Конфигурация с секретами: читает только root и группа приложения (640).
install -d -m 750 -o root -g "$APP_USER" "$CONFIG_DIR"

echo "==> 4/4 файл конфигурации"
if [[ ! -f "$CONFIG_DIR/warehouse.env" ]]; then
    install -m 640 -o root -g "$APP_USER" \
        "$(dirname "$0")/warehouse.env.example" "$CONFIG_DIR/warehouse.env"
    echo "    создан $CONFIG_DIR/warehouse.env — впишите в него реальные пароли"
fi

ls -ld "$APP_HOME" "$CONFIG_DIR" "$CONFIG_DIR/warehouse.env"

cat <<MSG

Среда готова. Дальше:
  1. Отредактируйте $CONFIG_DIR/warehouse.env (пароль БД, логин и пароль API).
  2. Выполните 20-deploy-app.sh — он выложит код, поставит зависимости,
     применит миграции и запустит сервис.
MSG
