#!/usr/bin/env bash
# Файл .env для CI: шаблон .env.example + пароли из защищённых переменных CI.
#
# Пароли в репозитории не хранятся. В GitHub они заданы как секреты
# CI_AUTH_PASSWORD и CI_POSTGRES_PASSWORD (Settings → Secrets and variables →
# Actions, см. scripts/setup_github.sh) и попадают сюда переменными окружения.
# GitHub маскирует их значения в журналах. Тег образа — версия и commit SHA.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${CI_AUTH_PASSWORD:?не задан секрет CI_AUTH_PASSWORD (scripts/setup_github.sh)}"
: "${CI_POSTGRES_PASSWORD:?не задан секрет CI_POSTGRES_PASSWORD (scripts/setup_github.sh)}"
for value in "$CI_AUTH_PASSWORD" "$CI_POSTGRES_PASSWORD"; do
    # пароль подставляется в строку подключения — только безопасные символы
    [[ "$value" =~ ^[A-Za-z0-9_-]{12,}$ ]] \
        || { echo "Секрет должен быть не короче 12 символов из [A-Za-z0-9_-]" >&2; exit 1; }
done

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' app/__init__.py)"
SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"
APP_VERSION="${VERSION}-${SHA:0:7}"

sed -e "s|^AUTH_PASSWORD=.*|AUTH_PASSWORD=${CI_AUTH_PASSWORD}|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${CI_POSTGRES_PASSWORD}|" \
    -e "s|://warehouse:warehouse@|://warehouse:${CI_POSTGRES_PASSWORD}@|" \
    -e "s|^APP_VERSION=.*|APP_VERSION=${APP_VERSION}|" \
    -e "s|^APP_ENV=.*|APP_ENV=ci|" \
    .env.example > .env
chmod 600 .env

grep -q "^APP_VERSION=${APP_VERSION}$" .env || { echo "APP_VERSION не записан в .env" >&2; exit 1; }
if grep -q 'warehouse:warehouse@' .env; then
    echo "В .env остался пароль из шаблона" >&2
    exit 1
fi
if [ -n "${GITHUB_ENV:-}" ]; then
    echo "APP_VERSION=${APP_VERSION}" >> "$GITHUB_ENV"
fi
echo "Создан .env для CI: образ warehouse-inventory:${APP_VERSION}, пароли из секретов CI"
