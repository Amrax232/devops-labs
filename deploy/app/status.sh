#!/usr/bin/env bash
# Быстрая диагностика: пригодится на защите и при разборе отказов.
set -uo pipefail

SERVICE_NAME="${SERVICE_NAME:-warehouse}"
DB_HOST="${DB_HOST:-192.168.56.11}"

echo "=== systemd ==="
systemctl --no-pager --lines=0 status "$SERVICE_NAME" || true

echo
echo "=== процесс и порт ==="
ss -ltnp | grep -E ':8000|State' || echo "порт 8000 никто не слушает"
pgrep -a uvicorn || echo "процесс uvicorn не найден"

echo
echo "=== последние записи журнала ==="
journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true

echo
echo "=== доступность приложения ==="
curl -fsS http://127.0.0.1:8000/healthz && echo || echo "healthz недоступен"
curl -fsS http://127.0.0.1:8000/readyz && echo || echo "readyz недоступен"

echo
echo "=== доступность базы данных ==="
if command -v pg_isready >/dev/null; then
    pg_isready -h "$DB_HOST" -p 5432 || true
fi

echo
echo "=== firewall ==="
ufw status verbose || true
