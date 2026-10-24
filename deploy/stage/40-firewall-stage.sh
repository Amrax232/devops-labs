#!/usr/bin/env bash
# Тестовое окружение (ЛР6), шаг 4: firewall.
#
# Входящие: SSH и HTTP 8080 — только из лабораторной сети 192.168.56.0/24.
# Runner работает исходящими соединениями — входящий доступ ему не нужен.
#
# Docker публикует порты в обход правил ufw (собственные цепочки iptables),
# поэтому главная защита — адрес публикации: Nginx слушает только
# HTTP_BIND=192.168.56.20 (stage.env), а не 0.0.0.0. Правило ufw ниже
# документирует намерение и действует для всех остальных сервисов машины.
#
# Запуск (от root):  bash 40-firewall-stage.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Скрипт нужно запускать от root" >&2; exit 1; }

ufw allow from 192.168.56.0/24 to any port 22 proto tcp comment "SSH из лабораторной сети"
ufw allow from 192.168.56.0/24 to any port 8080 proto tcp comment "staging: Nginx"
ufw --force enable
ufw status verbose
