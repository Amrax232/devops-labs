#!/usr/bin/env bash
# Тестовое окружение (ЛР6), шаг 1: Docker и утилиты проверки.
#
# Docker Engine и плагин compose — из официального репозитория Docker
# (в Debian 12 compose слишком старый для docker-compose.deploy.yml: нужен !reset).
# jq и curl нужны проверке релиза (scripts/smoke_test.sh), git — runner.
#
# Запуск (от root, после common/00-base-setup.sh stage):  bash 10-install-docker.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Скрипт нужно запускать от root" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "==> 1/3 репозиторий Docker"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg git jq
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list

echo "==> 2/3 Docker Engine и compose"
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> 3/3 журналы контейнеров с ротацией"
install -d -m 755 /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
JSON
systemctl enable --now docker
systemctl restart docker
docker version --format 'Docker {{.Server.Version}}'
docker compose version
