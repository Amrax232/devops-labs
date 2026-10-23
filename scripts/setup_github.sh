#!/usr/bin/env bash
# Настройка репозитория GitHub для CI (ЛР5) — один раз, владельцем репозитория:
#
#   gh auth login                                  # вход в GitHub CLI
#   ./scripts/setup_github.sh <логин1> <логин2> <логин3>
#
# Что делает:
#   1. записывает логины участников в .github/CODEOWNERS вместо заглушек;
#   2. создаёт защищённые переменные CI (секреты) CI_AUTH_PASSWORD и
#      CI_POSTGRES_PASSWORD со случайными значениями, если их ещё нет;
#   3. по умолчанию даёт pipeline только чтение репозитория (права на запись
#      в реестр выдаются явно одному этапу публикации);
#   4. создаёт окружение registry: публикация разрешена только из main;
#   5. защищает ветку main: только через merge request, обязательный итог CI
#      (ci-gate), одобрение владельца критических файлов (CODEOWNERS),
#      запрет force push и удаления ветки, правила действуют и для админов.
# Изменённый CODEOWNERS нужно закоммитить и отправить через merge request.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$#" -lt 2 ]; then
    echo "Использование: $0 <логин1> <логин2> [<логин3>]" >&2
    echo "Нужно минимум два участника: автор не может одобрить свой merge request." >&2
    exit 1
fi
command -v gh > /dev/null || { echo "Установите GitHub CLI: sudo apt install gh" >&2; exit 1; }
gh auth status > /dev/null 2>&1 || { echo "Выполните gh auth login" >&2; exit 1; }
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "Репозиторий: $REPO"

echo "==> 1/5 владельцы критических файлов"
owners=""
for login in "$@"; do owners+=" @${login#@}"; done
sed -i -E "s/(@CHANGE_ME_[0-9]+ ?)+/${owners# } /" .github/CODEOWNERS
sed -i -E 's/ +$//' .github/CODEOWNERS
grep -q @CHANGE_ME .github/CODEOWNERS && { echo "Заглушки остались" >&2; exit 1; }
echo "    .github/CODEOWNERS:${owners}"

echo "==> 2/5 защищённые переменные CI"
existing="$(gh secret list --repo "$REPO" --json name -q '.[].name')"
for name in CI_AUTH_PASSWORD CI_POSTGRES_PASSWORD; do
    if grep -qx "$name" <<< "$existing"; then
        echo "    $name уже задан"
    else
        gh secret set "$name" --repo "$REPO" --body "$(openssl rand -hex 16)"
        echo "    $name создан (случайное значение, в журналах CI маскируется)"
    fi
done

echo "==> 3/5 права pipeline по умолчанию — только чтение"
gh api -X PUT "repos/$REPO/actions/permissions/workflow" \
    -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false > /dev/null

echo "==> 4/5 окружение registry (публикация только из защищённой ветки)"
gh api -X PUT "repos/$REPO/environments/registry" --input - > /dev/null <<'JSON'
{"deployment_branch_policy": {"protected_branches": true, "custom_branch_policies": false}}
JSON

echo "==> 5/5 защита ветки main"
gh api -X PUT "repos/$REPO/branches/main/protection" --input - > /dev/null <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["ci-gate"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true,
    "require_last_push_approval": true
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "Готово. Закоммитьте .github/CODEOWNERS через merge request."
echo "Проверка: gh api repos/$REPO/branches/main/protection | head"
