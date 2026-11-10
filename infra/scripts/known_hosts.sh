#!/usr/bin/env bash
# Ключи SSH узлов окружения: infra/scripts/known_hosts.sh <staging|production>
#
# Добавляет ключи узлов в infra/known_hosts (файл в репозитории): Ansible
# подключается со строгой проверкой и не примет подменённый сервер.
# Сверьте отпечаток с консолью ВМ: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_NAME="${1:-}"
[[ "$ENV_NAME" =~ ^(staging|production)$ ]] || { echo "Использование: $0 staging|production" >&2; exit 1; }
touch known_hosts
for host in $(sed -n 's/^ansible_host: //p' inventories/"$ENV_NAME"/host_vars/*.yml); do
    ssh-keygen -R "$host" -f known_hosts > /dev/null 2>&1 || true
    ssh-keyscan -t ed25519 "$host" 2> /dev/null >> known_hosts
    echo "$host: $(ssh-keygen -lf <(grep "^$host " known_hosts) | awk '{print $2}')"
done
rm -f known_hosts.old
sort -u -o known_hosts known_hosts
echo "Сверьте отпечатки с консолью машины и закоммитьте infra/known_hosts"
