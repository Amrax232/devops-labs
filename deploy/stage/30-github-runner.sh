#!/usr/bin/env bash
# Тестовое окружение (ЛР6), шаг 3: GitHub Actions runner под пользователем deploy.
#
# Runner сам обращается к GitHub (исходящее HTTPS-соединение) и забирает
# задания — машине не нужен внешний IP, а входящих соединений с интернета нет.
# Метка staging: на этом runner выполняется только задание развёртывания
# (.github/workflows/deploy.yml, runs-on: [self-hosted, linux, staging]).
#
# Токен регистрации (действует 1 час) выдаёт GitHub:
#   Settings → Actions → Runners → New self-hosted runner, строка --token,
#   или: gh api -X POST repos/<владелец>/<репозиторий>/actions/runners/registration-token -q .token
#
# Запуск (от root):  bash 30-github-runner.sh https://github.com/<владелец>/<репозиторий> <токен>
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Скрипт нужно запускать от root" >&2; exit 1; }

REPO_URL="${1:-}"
TOKEN="${2:-}"
[[ "$REPO_URL" =~ ^https://github\.com/[^/]+/[^/]+$ && -n "$TOKEN" ]] || {
    echo "Использование: $0 https://github.com/<владелец>/<репозиторий> <токен регистрации>" >&2
    exit 1
}
DEPLOY_USER="${DEPLOY_USER:-deploy}"
RUNNER_DIR="${RUNNER_DIR:-/opt/actions-runner}"
id "$DEPLOY_USER" > /dev/null || { echo "Сначала: bash 20-deploy-user.sh" >&2; exit 1; }

echo "==> 1/4 последняя версия runner"
VERSION="$(curl -fsSLI -o /dev/null -w '%{url_effective}' \
    https://github.com/actions/runner/releases/latest | sed 's|.*/v||')"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Не удалось определить версию" >&2; exit 1; }
echo "    actions/runner $VERSION"

echo "==> 2/4 установка в $RUNNER_DIR"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$RUNNER_DIR"
ARCHIVE="actions-runner-linux-x64-$VERSION.tar.gz"
curl -fsSL -o "/tmp/$ARCHIVE" \
    "https://github.com/actions/runner/releases/download/v$VERSION/$ARCHIVE"
tar -xzf "/tmp/$ARCHIVE" -C "$RUNNER_DIR"
rm -f "/tmp/$ARCHIVE"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$RUNNER_DIR"
"$RUNNER_DIR/bin/installdependencies.sh" > /dev/null

echo "==> 3/4 регистрация (имя warehouse-stage, метки self-hosted, linux, staging)"
cd "$RUNNER_DIR"
sudo -u "$DEPLOY_USER" ./config.sh --unattended --replace \
    --url "$REPO_URL" --token "$TOKEN" \
    --name warehouse-stage --labels staging --work _work

echo "==> 4/4 служба systemd (запуск от $DEPLOY_USER)"
./svc.sh install "$DEPLOY_USER"
./svc.sh start
./svc.sh status | head -5
echo "Runner в списке: Settings → Actions → Runners (статус Idle)."
