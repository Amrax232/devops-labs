#!/usr/bin/env bash
# Сетевые ограничения сервера базы данных.
# Порт 5432 доступен ТОЛЬКО серверу приложения, всё остальное входящее закрыто.
set -euo pipefail

APP_IP="${APP_IP:-192.168.56.10}"

if [[ $EUID -ne 0 ]]; then
    echo "Скрипт нужно запускать от root" >&2
    exit 1
fi

ufw default deny incoming
ufw default allow outgoing
ufw allow from 192.168.56.0/24 to any port 22 proto tcp comment "SSH из лабораторной сети"
ufw allow from "${APP_IP}" to any port 5432 proto tcp comment "PostgreSQL только для приложения"
ufw --force enable
ufw status verbose
