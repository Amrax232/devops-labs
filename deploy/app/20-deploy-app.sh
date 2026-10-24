#!/usr/bin/env bash
# Выкладка приложения: код, зависимости, миграции, systemd-сервис.
# Скрипт идемпотентен: первый запуск разворачивает, последующие обновляют.
#
# Запуск (от root на машине warehouse-app):
#   REPO_URL=https://github.com/<логин>/warehouse-inventory.git bash 20-deploy-app.sh
set -euo pipefail

APP_USER="${APP_USER:-warehouse}"
APP_HOME="${APP_HOME:-/opt/warehouse}"
APP_DIR="${APP_DIR:-$APP_HOME/current}"
VENV_DIR="${VENV_DIR:-$APP_HOME/venv}"
CONFIG_FILE="${CONFIG_FILE:-/etc/warehouse/warehouse.env}"
REPO_URL="${REPO_URL:-}"
REPO_REF="${REPO_REF:-main}"
SERVICE_NAME="warehouse"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/healthz}"

if [[ $EUID -ne 0 ]]; then
    echo "Скрипт нужно запускать от root" >&2
    exit 1
fi
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Нет файла конфигурации $CONFIG_FILE — сначала выполните 10-install-runtime.sh" >&2
    exit 1
fi
if grep -q CHANGE_ME "$CONFIG_FILE"; then
    echo "В $CONFIG_FILE остались заглушки CHANGE_ME — впишите реальные пароли" >&2
    exit 1
fi

echo "==> 1/6 получение кода (${REPO_REF})"
if [[ -d "$APP_DIR/.git" ]]; then
    sudo -u "$APP_USER" git -C "$APP_DIR" fetch --quiet origin "$REPO_REF"
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard --quiet "origin/${REPO_REF}"
else
    if [[ -z "$REPO_URL" ]]; then
        echo "Укажите репозиторий: REPO_URL=... bash $0" >&2
        exit 1
    fi
    rm -rf "${APP_DIR:?}"/*
    sudo -u "$APP_USER" git clone --quiet --branch "$REPO_REF" "$REPO_URL" "$APP_DIR"
fi
echo "    версия: $(git -C "$APP_DIR" log --oneline -1)"

echo "==> 2/6 виртуальное окружение и зависимости"
if [[ ! -d "$VENV_DIR" ]]; then
    sudo -u "$APP_USER" python3 -m venv "$VENV_DIR"
fi
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> 3/6 миграции базы данных"
# Переменные читаются из того же файла, что использует сервис.
set -a
# shellcheck disable=SC1090
source "$CONFIG_FILE"
set +a
(cd "$APP_DIR" && sudo -u "$APP_USER" --preserve-env=DATABASE_URL \
    "$VENV_DIR/bin/alembic" upgrade head)

echo "==> 4/6 установка unit-файла"
install -m 644 -o root -g root "$(dirname "$0")/warehouse.service" \
    "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null

echo "==> 5/6 перезапуск сервиса"
systemctl restart "$SERVICE_NAME"
sleep 3
systemctl --no-pager --lines=0 status "$SERVICE_NAME"

echo "==> 6/6 проверка работоспособности"
for attempt in 1 2 3 4 5; do
    if curl -fsS "$HEALTH_URL" >/dev/null; then
        echo "    health-check пройден: $(curl -fsS "$HEALTH_URL")"
        exit 0
    fi
    echo "    попытка $attempt из 5 не удалась, ждём 3 секунды..."
    sleep 3
done

echo "Приложение не отвечает. Смотрите журнал: journalctl -u ${SERVICE_NAME} -n 50" >&2
exit 1
