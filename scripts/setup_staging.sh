#!/usr/bin/env bash
# Настройка GitHub для непрерывной поставки (ЛР6) — один раз, владельцем репозитория:
#
#   ./scripts/setup_staging.sh [--approve <логин>]...
#
#   0. владельцы каталога deploy/ в .github/CODEOWNERS — те же, что у Makefile
#      (изменённый CODEOWNERS нужно закоммитить через merge request);
#   1. окружение staging: развёртывание только из защищённой ветки main;
#      с --approve — ещё и ручное подтверждение каждого выпуска этим участником;
#   2. переменная STAGING_URL — адрес тестового окружения (ссылка в запуске);
#   3. запуски из форков — только после одобрения (self-hosted runner не должен
#      выполнять чужой код);
#   4. токен регистрации runner для deploy/stage/30-github-runner.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

reviewers=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --approve) reviewers+=("$2"); shift 2 ;;
        *) echo "Использование: $0 [--approve <логин>]..." >&2; exit 1 ;;
    esac
done
command -v gh > /dev/null || { echo "Установите GitHub CLI: sudo apt install gh" >&2; exit 1; }
gh auth status > /dev/null 2>&1 || { echo "Выполните gh auth login" >&2; exit 1; }
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
STAGING_URL="${STAGING_URL:-http://192.168.56.20:8080}"
echo "Репозиторий: $REPO"

echo "==> 0/4 владельцы deploy/ в CODEOWNERS"
if grep -q '^/deploy/' .github/CODEOWNERS; then
    echo "    уже есть: $(grep '^/deploy/' .github/CODEOWNERS)"
else
    owners="$(awk '$1 == "/Makefile" {$1 = ""; print substr($0, 2)}' .github/CODEOWNERS)"
    [ -n "$owners" ] || { echo "В CODEOWNERS нет владельцев /Makefile: scripts/setup_github.sh" >&2; exit 1; }
    printf '\n# Развёртывание в тестовое окружение (ЛР6)\n%-29s %s\n' "/deploy/" "$owners" \
        >> .github/CODEOWNERS
    echo "    добавлено: /deploy/ $owners — закоммитьте .github/CODEOWNERS"
fi

echo "==> 1/4 окружение staging"
reviewers_json="[]"
if [ "${#reviewers[@]}" -gt 0 ]; then
    reviewers_json="["
    for login in "${reviewers[@]}"; do
        id="$(gh api "users/${login#@}" -q .id)"
        reviewers_json+="{\"type\":\"User\",\"id\":$id},"
    done
    reviewers_json="${reviewers_json%,}]"
fi
gh api -X PUT "repos/$REPO/environments/staging" --input - > /dev/null <<JSON
{
  "deployment_branch_policy": {"protected_branches": true, "custom_branch_policies": false},
  "reviewers": $reviewers_json
}
JSON
echo "    только из защищённой ветки; подтверждают: ${reviewers[*]:-не требуется}"

echo "==> 2/4 переменная STAGING_URL = $STAGING_URL"
gh variable set STAGING_URL --env staging --repo "$REPO" --body "$STAGING_URL"

echo "==> 3/4 запуски из форков — только с одобрения"
gh api -X PUT "repos/$REPO/actions/permissions/fork-pr-contributor-approval" \
    -f approval_policy=all_external_contributors > /dev/null \
    || echo "    не удалось изменить через API: Settings → Actions → General →" \
            "«Require approval for all external contributors»"

echo "==> 4/4 токен регистрации runner (действует 1 час)"
token="$(gh api -X POST "repos/$REPO/actions/runners/registration-token" -q .token)"
echo "    на сервере staging (от root):"
echo "    bash deploy/stage/30-github-runner.sh https://github.com/$REPO $token"
