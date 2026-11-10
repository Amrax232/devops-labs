#!/usr/bin/env bash
# Секреты окружения: infra/scripts/vault_init.sh <staging|production>
#
# Создаёт inventories/<окружение>/group_vars/<окружение>/vault.yml со случайными
# паролями и СРАЗУ шифрует его (ansible-vault, AES-256). Незашифрованный файл
# существует только во временном каталоге и удаляется.
# Пароль vault — ~/.config/warehouse/vault-<окружение>.pass (вне репозитория,
# права 600); тот же пароль — секрет CI ANSIBLE_VAULT_PASSWORD окружения
# infra-<окружение>. Изменить секреты: make vault-edit ENV=<окружение>.
#
# Чтобы сохранить пароли уже работающего окружения (например, staging из ЛР6),
# передайте файл его настроек: FROM_ENV_FILE=/путь/stage.env
#
# infra/scripts/vault_init.sh <окружение> --upgrade — дополнить уже созданный
# vault.yml секретами, которые появились позже (пароль Grafana, ЛР8): случайные
# значения добавляются только для отсутствующих ключей, остальные не меняются.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_NAME="${1:-}"
MODE="${2:-}"
[[ "$ENV_NAME" =~ ^(staging|production)$ && "$MODE" =~ ^(|--upgrade)$ ]] \
    || { echo "Использование: $0 staging|production [--upgrade]" >&2; exit 1; }
VAULT="inventories/$ENV_NAME/group_vars/$ENV_NAME/vault.yml"
PASS_FILE="${VAULT_PASS:-$HOME/.config/warehouse/vault-$ENV_NAME.pass}"
ANSIBLE_VAULT_BIN="${ANSIBLE_VAULT_BIN:-.venv/bin/ansible-vault}"
[ -x "$ANSIBLE_VAULT_BIN" ] || { echo "Нет Ansible: make infra-setup" >&2; exit 1; }

random() { openssl rand -hex 16; }
# Секреты, добавленные после ЛР7: имя ключа → создаётся случайное значение
LATER_KEYS=(vault_warehouse_grafana_admin_password)

if [ "$MODE" = --upgrade ]; then
    [ -f "$VAULT" ] || { echo "Нет $VAULT — создать: make vault-init ENV=$ENV_NAME" >&2; exit 1; }
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    "$ANSIBLE_VAULT_BIN" decrypt --vault-id "$ENV_NAME@$PASS_FILE" --output "$TMP/vault.yml" "$VAULT"
    added=()
    for key in "${LATER_KEYS[@]}"; do
        grep -q "^$key:" "$TMP/vault.yml" && continue
        echo "$key: \"$(random)\"" >> "$TMP/vault.yml"
        added+=("$key")
    done
    if [ "${#added[@]}" -eq 0 ]; then
        echo "В $VAULT уже есть все секреты — изменений нет"
        exit 0
    fi
    "$ANSIBLE_VAULT_BIN" encrypt --vault-id "$ENV_NAME@$PASS_FILE" --output "$VAULT" "$TMP/vault.yml"
    head -1 "$VAULT"
    echo "Добавлены секреты: ${added[*]} (посмотреть: make vault-view ENV=$ENV_NAME)"
    exit 0
fi
[ ! -f "$VAULT" ] || { echo "$VAULT уже есть — изменить: make vault-edit ENV=$ENV_NAME" >&2; exit 1; }

if [ ! -f "$PASS_FILE" ]; then
    mkdir -p "$(dirname "$PASS_FILE")" && chmod 700 "$(dirname "$PASS_FILE")"
    (umask 077 && openssl rand -base64 32 > "$PASS_FILE")
    echo "Создан пароль vault: $PASS_FILE (сохраните его — без него секреты не расшифровать)"
fi

from_env() { [ -n "${FROM_ENV_FILE:-}" ] && sed -n "s/^$1=//p" "$FROM_ENV_FILE" | tail -1; }
auth="$(from_env AUTH_PASSWORD || true)"
pg="$(from_env POSTGRES_PASSWORD || true)"
salt="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9./' | head -c 16)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/vault.yml" <<YAML
---
vault_warehouse_auth_password: "${auth:-$(random)}"
vault_warehouse_postgres_password: "${pg:-$(random)}"
vault_warehouse_grafana_admin_password: "$(random)"
vault_users_admin_password: "$(random)"
vault_users_admin_password_salt: "$salt"
vault_warehouse_registry_token: "${REGISTRY_TOKEN:-}"
YAML
"$ANSIBLE_VAULT_BIN" encrypt --vault-id "$ENV_NAME@$PASS_FILE" \
    --output "$VAULT" "$TMP/vault.yml"
head -1 "$VAULT"
echo "Создан зашифрованный $VAULT. Пароль sudo администратора: make vault-view ENV=$ENV_NAME"
echo "Пароль vault для CI: gh secret set ANSIBLE_VAULT_PASSWORD --env infra-$ENV_NAME < $PASS_FILE"
