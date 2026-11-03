#!/usr/bin/env bash
# Настройка репозитория для инфраструктурного кода (ЛР7) — один раз:
#
#   ./scripts/setup_infra.sh --approve <логин> [--approve <логин>]...
#
#   1. владелец репозитория в параметрах Ansible (адрес образа ghcr.io, URL);
#   2. владельцы каталога infra/ в .github/CODEOWNERS (как у Makefile):
#      роли, шаблоны и секретные настройки меняются только с их одобрением;
#   3. окружения GitHub infra-staging и infra-production: только ветка main и
#      ОБЯЗАТЕЛЬНОЕ подтверждение каждого применения указанными участниками;
#   4. секреты окружений: ключ ansible и пароль vault — из файлов на этой
#      машине (infra/scripts/keygen.sh, make vault-init), если они уже есть.
# Изменённые файлы закоммитьте через merge request.
set -euo pipefail
cd "$(dirname "$0")/.."

reviewers=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --approve) reviewers+=("${2#@}"); shift 2 ;;
        *) echo "Использование: $0 --approve <логин> [--approve <логин>]..." >&2; exit 1 ;;
    esac
done
[ "${#reviewers[@]}" -gt 0 ] || { echo "Нужен хотя бы один --approve <логин>" >&2; exit 1; }
command -v gh > /dev/null || { echo "Установите GitHub CLI: sudo apt install gh" >&2; exit 1; }
gh auth status > /dev/null 2>&1 || { echo "Выполните gh auth login" >&2; exit 1; }
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
OWNER="${REPO%%/*}"
echo "Репозиторий: $REPO"

echo "==> 1/4 владелец репозитория в параметрах Ansible"
owner_lc="$(tr '[:upper:]' '[:lower:]' <<< "$OWNER")"
sed -i "s#ghcr.io/CHANGE_ME/#ghcr.io/$owner_lc/#; s#https://github.com/CHANGE_ME/warehouse-inventory#https://github.com/$REPO#" \
    infra/group_vars/all/common.yml infra/inventories/*/group_vars/*/main.yml
grep -h 'ghcr.io\|github.com' infra/group_vars/all/common.yml infra/inventories/*/group_vars/*/main.yml | sed 's/^/    /'

echo "==> 2/4 владельцы infra/ в CODEOWNERS"
if grep -q '^/infra/' .github/CODEOWNERS; then
    echo "    уже есть: $(grep '^/infra/' .github/CODEOWNERS)"
else
    owners="$(awk '$1 == "/Makefile" {$1 = ""; print substr($0, 2)}' .github/CODEOWNERS)"
    [ -n "$owners" ] || { echo "В CODEOWNERS нет владельцев /Makefile: scripts/setup_github.sh" >&2; exit 1; }
    printf '\n# Инфраструктура как код (ЛР7): роли, шаблоны, секреты окружений\n%-29s %s\n' \
        "/infra/" "$owners" >> .github/CODEOWNERS
    echo "    добавлено: /infra/ $owners"
fi

echo "==> 3/4 окружения infra-staging и infra-production (подтверждают: ${reviewers[*]})"
reviewers_json=""
for login in "${reviewers[@]}"; do
    reviewers_json+="{\"type\":\"User\",\"id\":$(gh api "users/$login" -q .id)},"
done
for env in staging production; do
    gh api -X PUT "repos/$REPO/environments/infra-$env" --input - > /dev/null <<JSON
{
  "deployment_branch_policy": {"protected_branches": true, "custom_branch_policies": false},
  "reviewers": [${reviewers_json%,}]
}
JSON
    echo "    infra-$env: только main, подтверждение обязательно"
done

echo "==> 4/4 секреты окружений"
for env in staging production; do
    key="$HOME/.ssh/warehouse_ansible_$env"
    pass="$HOME/.config/warehouse/vault-$env.pass"
    if [ -f "$key" ]; then
        gh secret set ANSIBLE_SSH_PRIVATE_KEY --env "infra-$env" --repo "$REPO" < "$key"
        echo "    infra-$env: ANSIBLE_SSH_PRIVATE_KEY"
    else
        echo "    infra-$env: нет $key — сначала make infra-keygen ENV=$env"
    fi
    if [ -f "$pass" ]; then
        gh secret set ANSIBLE_VAULT_PASSWORD --env "infra-$env" --repo "$REPO" < "$pass"
        echo "    infra-$env: ANSIBLE_VAULT_PASSWORD"
    else
        echo "    infra-$env: нет $pass — сначала make vault-init ENV=$env"
    fi
done
