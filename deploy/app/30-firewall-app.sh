#!/usr/bin/env bash
# Сетевые ограничения сервера приложения.
# Снаружи доступны только SSH (из лабораторной сети) и порт приложения.
set -euo pipefail

APP_PORT="${APP_PORT:-8000}"

if [[ $EUID -ne 0 ]]; then
    echo "Скрипт нужно запускать от root" >&2
    exit 1
fi

ufw default deny incoming
ufw default allow outgoing
ufw allow from 192.168.56.0/24 to any port 22 proto tcp comment "SSH из лабораторной сети"
ufw allow "${APP_PORT}"/tcp comment "HTTP API приложения"
ufw --force enable
ufw status verbose
