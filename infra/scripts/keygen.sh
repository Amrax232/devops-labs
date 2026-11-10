#!/usr/bin/env bash
# Ключи SSH для окружения: infra/scripts/keygen.sh <staging|production>
#
#   1. ключ служебной учётной записи ansible этого окружения:
#      ~/.ssh/warehouse_ansible_<окружение> (закрытый — только у управляющей
#      машины и в секрете CI), открытый — в параметры окружения;
#   2. открытый ключ администратора (~/.ssh/warehouse.pub из ЛР2 или
#      ~/.ssh/id_ed25519.pub) — в общие параметры вместо заглушки.
# Открытые ключи — не секрет, их можно и нужно хранить в репозитории.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_NAME="${1:-}"
[[ "$ENV_NAME" =~ ^(staging|production)$ ]] || { echo "Использование: $0 staging|production" >&2; exit 1; }
VARS="inventories/$ENV_NAME/group_vars/$ENV_NAME/main.yml"
KEY="$HOME/.ssh/warehouse_ansible_$ENV_NAME"

mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
if [ ! -f "$KEY" ]; then
    ssh-keygen -q -t ed25519 -N "" -C "ansible@warehouse-$ENV_NAME" -f "$KEY"
    echo "Создан ключ $KEY"
fi
pub="$(cat "$KEY.pub")"
sed -i "s|^users_ansible_public_key: .*|users_ansible_public_key: \"$pub\"|" "$VARS"
echo "Открытый ключ ansible записан в $VARS"

if grep -q CHANGE_ME_ADMIN_PUBLIC_KEY group_vars/all/common.yml; then
    for candidate in "$HOME/.ssh/warehouse.pub" "$HOME/.ssh/id_ed25519.pub"; do
        if [ -f "$candidate" ]; then
            sed -i "s|\"CHANGE_ME_ADMIN_PUBLIC_KEY\"|\"$(cat "$candidate")\"|" group_vars/all/common.yml
            echo "Ключ администратора deployer: $candidate"
            break
        fi
    done
    grep -q CHANGE_ME_ADMIN_PUBLIC_KEY group_vars/all/common.yml \
        && echo "ВНИМАНИЕ: нет ~/.ssh/warehouse.pub — создайте: ssh-keygen -t ed25519 -f ~/.ssh/warehouse" >&2
fi
echo "Закрытый ключ для CI (секрет ANSIBLE_SSH_PRIVATE_KEY окружения infra-$ENV_NAME):"
echo "  gh secret set ANSIBLE_SSH_PRIVATE_KEY --env infra-$ENV_NAME < $KEY"
