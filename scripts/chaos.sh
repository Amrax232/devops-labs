#!/usr/bin/env bash
# Учебные сбои для тренировки диагностики (ЛР8): make chaos SCENARIO=<сбой>
#
# На защите сбой создаёт преподаватель или напарник — заранее неизвестный.
# Этот скрипт нужен, чтобы ДО защиты пройти каждый сценарий по инструкции
# docs/runbook.md: увидеть оповещение, найти компонент по метрикам и журналам,
# подтвердить причину и восстановить работу.
#
#   traffic [секунд]   фоновая нагрузка (чтение каталога) — без неё не видно
#                      ни доли ошибок, ни времени ответа
#   db-stop            остановить PostgreSQL                   → runbook #2
#   config             app1 с неверным паролем БД (ошибка конфигурации) → #2, #4
#   restart            аварийное завершение процесса в app1    → #4
#   memory [секунд]    app1 занимает ~93% лимита памяти        → #5
#   oom                app1 превышает лимит памяти (OOM)       → #4, #5
#   hang               app2 «зависает» (docker pause): healthcheck не проходит → #4
#   port               Nginx остановлен: порт сервиса не отвечает → #1, #8
#   auth [запросов]    подбор пароля: серия запросов с неверным паролем → #7
#   secret             в журнал app1 попадает строка с паролем в адресе БД → #9
#   disk               заполнить диск хоста до ~92% (только ВМ, CONFIRM=1) → #3
#   recover            отменить все учебные сбои
#
# PROJECT — проект compose (warehouse-inventory локально, warehouse-stage на ВМ).
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${PROJECT:-warehouse-inventory}"
HTTP_PORT="${HTTP_PORT:-$(sed -n 's/^HTTP_PORT=//p' .env 2> /dev/null | tail -1 || true)}"
URL="${URL:-http://127.0.0.1:${HTTP_PORT:-8080}}"
FILL_FILE="${FILL_FILE:-/var/tmp/warehouse-chaos.fill}"
OVERRIDE="$(mktemp --suffix=.yml)"
trap 'rm -f "$OVERRIDE"' EXIT

c() { echo "$PROJECT-$1-1"; }
say() { printf '==> %s\n' "$*"; }
hint() { printf '    что смотреть: %s\n' "$*"; }

# процесс-нагрузка на память внутри контейнера: доля лимита cgroup и время
memory_hog() {  # <контейнер> <доля лимита> <секунд>
    docker exec "$1" python - "$2" "$3" <<'PY'
import sys, time
share, hold = float(sys.argv[1]), int(sys.argv[2])
limit = int(open("/sys/fs/cgroup/memory.max").read())
current = lambda: int(open("/sys/fs/cgroup/memory.current").read())
chunks = []
while current() < share * limit:
    chunks.append(bytearray(b"\x01") * (8 * 2**20))   # 8 МиБ, страницы заняты
print(f"занято {current() / limit:.0%} лимита {limit // 2**20} МиБ, держу {hold} с", flush=True)
time.sleep(hold)
PY
}

traffic() {
    local seconds="${1:-300}" end
    end=$((SECONDS + seconds))
    say "нагрузка на $URL в течение $seconds с (Ctrl+C — остановить)"
    while [ "$SECONDS" -lt "$end" ]; do
        for path in /api/v1/materials /api/v1/suppliers /api/v1/reports/stock /healthz; do
            curl -s -o /dev/null --max-time 5 "$URL$path" || true
        done
        sleep 0.2
    done
}

case "${1:-}" in
    traffic) traffic "${2:-300}" ;;
    db-stop)
        docker stop "$(c db)"
        hint "оповещения DatabaseUnavailable, WarehouseNotReady; /readyz 503; make logs-find LEVEL=ERROR" ;;
    config)
        cat > "$OVERRIDE" <<'YAML'
services:
  app1:
    environment:
      DATABASE_URL: postgresql+psycopg2://warehouse:wrong-password@db:5432/warehouse
YAML
        docker compose -p "$PROJECT" -f docker-compose.yml -f "$OVERRIDE" up -d --no-deps app1
        hint "app1 unhealthy, WarehouseNotReady (app1), в журнале app1 — db_unavailable; app2 работает" ;;
    restart)
        docker exec "$(c app1)" python -c "
import os, signal
for pid in filter(str.isdigit, os.listdir('/proc')):
    if int(pid) > 1 and b'uvicorn' in open(f'/proc/{pid}/cmdline', 'rb').read():
        os.kill(int(pid), signal.SIGKILL)"
        hint "ContainerRestarted, перезапусков=1 в make status; docker inspect $(c app1)" ;;
    memory)
        say "app1: память до 93% лимита на ${2:-180} с"
        memory_hog "$(c app1)" 0.93 "${2:-180}"
        hint "ContainerMemoryNearLimit (через 2 минуты), панель «Память контейнеров»" ;;
    oom)
        say "app1: память выше лимита — процесс будет убит ядром (OOM)"
        memory_hog "$(c app1)" 1.5 60 || echo "    процесс завершён: код $? (137 — OOM)"
        hint "container_oom_events_total, docker inspect -f '{{.State.OOMKilled}}' $(c app1), dmesg | grep -i oom" ;;
    hang)
        docker pause "$(c app2)"
        hint "app2 unhealthy, WarehouseInstanceDown, WarehouseNotReady (app2); Nginx отправляет запросы в app1" ;;
    port)
        docker stop "$(c nginx)"
        hint "curl $URL/healthz — соединение отклонено; WarehouseUnavailable; ss -ltn | grep ${HTTP_PORT:-8080}" ;;
    auth)
        say "${2:-30} запросов с неверным паролем"
        WRONG="wrong-$RANDOM"
        for _ in $(seq 1 "${2:-30}"); do
            curl -s -o /dev/null -u "admin:$WRONG" -X POST -H 'Content-Type: application/json' \
                -d '{}' "$URL/api/v1/units" || true
            sleep 0.1
        done
        hint "AuthFailuresBurst, make logs-find EVENT=auth_failed, коды 401 на панели" ;;
    secret)
        # строка в обход журналирования приложения (как print() в коде) — маскирование
        # её не видит, находит проверка журналов
        docker exec "$(c app1)" sh -c 'printf "%s\n" "{\"level\":\"DEBUG\",\"message\":\"connect postgresql://warehouse:Chaos-Leak-$(date +%s)@db:5432/warehouse\"}" > /proc/1/fd/1'
        hint "make logs-secrets → ПОДОЗРЕНИЕ в журнале app1" ;;
    disk)
        [ "${CONFIRM:-0}" = 1 ] || { echo "Сценарий заполняет диск хоста. Только на ВМ: CONFIRM=1 $0 disk" >&2; exit 1; }
        read -r size avail < <(df -B1 --output=size,avail "$(dirname "$FILL_FILE")" | tail -1)
        fill=$((avail - size * 8 / 100))
        [ "$fill" -gt 0 ] || { echo "свободно уже меньше 8%"; exit 0; }
        [ "$fill" -le $((40 * 2**30)) ] || { echo "нужно занять больше 40 ГБ — сценарий не для этого диска" >&2; exit 1; }
        fallocate -l "$fill" "$FILL_FILE"
        df -h "$(dirname "$FILL_FILE")"
        hint "DiskSpaceLow, панель «Хост: диск»; df -h; du -xsh /var/* | sort -h" ;;
    recover)
        say "отмена учебных сбоев"
        rm -f "$FILL_FILE"
        docker unpause "$(c app2)" 2> /dev/null || true
        docker start "$(c db)" "$(c nginx)" > /dev/null 2>&1 || true
        docker compose -p "$PROJECT" up -d --no-deps app1 2>&1 | sed 's/^/    /' || true
        ./scripts/compose_wait.sh -p "$PROJECT" ;;
    *) awk 'NR > 1 && /^#/ {sub(/^# ?/, ""); print; next} NR > 1 {exit}' "$0"; exit 1 ;;
esac
