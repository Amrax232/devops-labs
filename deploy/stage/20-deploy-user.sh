#!/usr/bin/env bash
# Тестовое окружение (ЛР6), шаг 2: отдельная учётная запись deploy и каталоги.
#
# deploy — системный пользователь, от имени которого работает GitHub runner
# и выполняется развёртывание:
#   - без пароля и без входа по SSH (AllowUsers разрешает только deployer);
#   - без sudo; состоит только в группе docker — это нужно для docker compose.
#     Группа docker равна по силе root на этой машине, поэтому на машине нет
#     ничего, кроме тестового окружения, и runner выполняет только задание CD;
#   - владеет /opt/warehouse-stage, файл настроек env/stage.env — права 600.
#
# Запуск (от root):
#   bash 20-deploy-user.sh ghcr.io/<владелец-в-нижнем-регистре>/warehouse-inventory
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Скрипт нужно запускать от root" >&2; exit 1; }

REGISTRY_IMAGE="${1:-}"
[[ "$REGISTRY_IMAGE" =~ ^ghcr\.io/[a-z0-9_.-]+/warehouse-inventory$ ]] || {
    echo "Использование: $0 ghcr.io/<владелец-в-нижнем-регистре>/warehouse-inventory" >&2
    exit 1
}
DEPLOY_USER="${DEPLOY_USER:-deploy}"
STAGE_DIR="${STAGE_DIR:-/opt/warehouse-stage}"
TEMPLATE="$(dirname "$0")/stage.env.example"

echo "==> 1/3 пользователь $DEPLOY_USER"
if ! id "$DEPLOY_USER" > /dev/null 2>&1; then
    adduser --system --group --home "/home/$DEPLOY_USER" --shell /usr/sbin/nologin \
        --gecos "CD: развёртывание тестового окружения" "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
passwd -l "$DEPLOY_USER" > /dev/null
id "$DEPLOY_USER"

echo "==> 2/3 каталоги $STAGE_DIR"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" \
    "$STAGE_DIR" "$STAGE_DIR/releases" "$STAGE_DIR/state" "$STAGE_DIR/backups"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$STAGE_DIR/env"

echo "==> 3/3 настройки окружения $STAGE_DIR/env/stage.env"
ENV_FILE="$STAGE_DIR/env/stage.env"
if [ -f "$ENV_FILE" ]; then
    echo "    уже существует — не изменяется"
else
    sed -e "s|^REGISTRY_IMAGE=.*|REGISTRY_IMAGE=$REGISTRY_IMAGE|" \
        -e "s|^AUTH_PASSWORD=.*|AUTH_PASSWORD=$(openssl rand -hex 16)|" \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 16)|" \
        "$TEMPLATE" > "$ENV_FILE"
    chown "$DEPLOY_USER:$DEPLOY_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "    создан со случайными паролями (посмотреть: sudo cat $ENV_FILE)"
fi
ls -la "$STAGE_DIR" "$STAGE_DIR/env"
