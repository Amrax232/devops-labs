#!/usr/bin/env bash
# Состояние системы по метрикам, оповещениям и журналам (ЛР8).
#
#   scripts/obs.sh status              сводка: контейнеры, доступность, цели сбора
#                                      метрик, оповещения, ключевые метрики, ошибки
#   scripts/obs.sh alerts              сработавшие оповещения
#   scripts/obs.sh targets             цели сбора метрик Prometheus и их состояние
#   scripts/obs.sh query '<PromQL>'    произвольный запрос к Prometheus
#   scripts/obs.sh snapshot <имя>      состояние системы в $REPORTS_DIR/release-<имя>-<время>.md
#                                      (до и после выпуска: make release-snapshot NAME=before);
#                                      REPORTS_DIR по умолчанию reports/
#
# Prometheus наружу не публикуется: запросы выполняются из его контейнера
# (docker exec, только чтение). PROJECT — имя проекта compose:
# warehouse-inventory (локально), warehouse-stage, warehouse-prod.
# URL — адрес Nginx (по умолчанию http://127.0.0.1:<HTTP_PORT из .env или 8080>).
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${PROJECT:-warehouse-inventory}"
PROM="$PROJECT-prometheus-1"
HTTP_PORT="${HTTP_PORT:-$(sed -n 's/^HTTP_PORT=//p' .env 2> /dev/null | tail -1 || true)}"
URL="${URL:-http://127.0.0.1:${HTTP_PORT:-8080}}"
REPORTS_DIR="${REPORTS_DIR:-reports}"
command -v jq > /dev/null || { echo "Нужен jq: sudo apt-get install -y jq" >&2; exit 1; }

prom() {  # GET /api/v1/<путь> из контейнера Prometheus
    docker exec "$PROM" wget -qO- "http://127.0.0.1:9090/api/v1/$1" 2> /dev/null
}
query() {
    prom "query?query=$(jq -rn --arg q "$1" '$q | @uri')"
}
value() {  # одно число: value '<PromQL>' [формат printf]
    local v
    v="$(query "$1" | jq -r '.data.result[0].value[1] // empty' 2> /dev/null || true)"
    # shellcheck disable=SC2059  # формат числа задаёт вызывающий
    if [ -z "$v" ] || [ "$v" = NaN ]; then echo "нет данных"; else printf "${2:-%s}" "$v"; fi
}
section() { printf '\n== %s\n' "$1"; }
prom_ready() {
    docker exec "$PROM" wget -qO- http://127.0.0.1:9090/-/ready > /dev/null 2>&1
}

containers() {
    docker ps -a --filter "label=com.docker.compose.project=$PROJECT" \
        --format '{{.Names}}' | sort | while read -r name; do
        docker inspect -f '{{.Name}}  {{.State.Status}}  {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}  перезапусков={{.RestartCount}}  OOMKilled={{.State.OOMKilled}}  код={{.State.ExitCode}}  образ={{.Config.Image}}' "$name" \
            | sed 's|^/|  |'
    done
}

availability() {
    local path code
    for path in /healthz /readyz /version; do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL$path" || true)"
        printf '  %-9s %s\n' "$path" "${code:-нет ответа}"
    done
    curl -s --max-time 5 "$URL/version" | jq -c . 2> /dev/null | sed 's/^/  версия: /' || true
}

targets() {
    prom 'targets?state=active' | jq -r '.data.activeTargets[]
        | "  \(.health | if . == "up" then "up  " else "DOWN" end)  \(.labels.job)  \(.labels.target // .labels.instance)  \(.lastError)"'
}

alerts() {
    local out
    out="$(prom alerts | jq -r '.data.alerts[]
        | "  \(.state)  \(.labels.severity)  \(.labels.alertname)  \(.annotations.summary)  → \(.annotations.runbook)"')"
    echo "${out:-  нет сработавших оповещений}"
}

key_metrics() {
    echo "  запросов в секунду (1 мин):   $(value 'sum(rate(warehouse_http_requests_total[1m]))' '%.2f')"
    echo "  ошибки 5xx, % (5 мин):        $(value '100 * sum(rate(warehouse_http_requests_total{status=~"5.."}[5m])) / sum(rate(warehouse_http_requests_total[5m]))' '%.2f')"
    echo "  отказы 4xx, % (5 мин):        $(value '100 * sum(rate(warehouse_http_requests_total{status=~"4.."}[5m])) / sum(rate(warehouse_http_requests_total[5m]))' '%.2f')"
    echo "  время ответа p95, с (5 мин):  $(value 'histogram_quantile(0.95, sum by (le) (rate(warehouse_http_request_duration_seconds_bucket[5m])))' '%.3f')"
    echo "  база доступна (1/0):          $(value 'max(warehouse_database_up)')"
    echo "  материалов ниже минимума:     $(value 'max(warehouse_materials_below_min)')"
    echo "  свободно на диске /, %:       $(value 'min(100 * node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})' '%.1f')"
    echo "  память контейнеров, % лимита:"
    query 'topk(5, 100 * container_memory_working_set_bytes{name=~".+"} / (container_spec_memory_limit_bytes{name=~".+"} > 0))' \
        | jq -r '.data.result[] | "    \(.metric.name)  \(.value[1] | tonumber | . * 10 | round / 10)%"' || true
}

status() {
    section "Контейнеры ($PROJECT)"
    containers
    section "Доступность через Nginx ($URL)"
    availability
    if ! prom_ready; then
        section "Prometheus"
        echo "  недоступен ($PROM) — метрик и оповещений нет: make ps, make logs S=prometheus"
    else
        section "Цели сбора метрик"
        targets
        section "Оповещения"
        alerts
        section "Ключевые метрики"
        key_metrics
    fi
    section "Ошибки в журналах за 15 минут (последние 10)"
    PROJECT="$PROJECT" ./scripts/logs.sh -l ERROR -t 15m -n 10 || true
}

snapshot() {
    local name="${1:?укажите имя: before или after}" file
    [[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "имя — буквы, цифры, - и _" >&2; exit 1; }
    mkdir -p "$REPORTS_DIR"
    file="$REPORTS_DIR/release-$name-$(date +%Y%m%d-%H%M%S).md"
    {
        echo "# Состояние системы: $name"
        echo
        echo "- время: $(date -Iseconds)"
        echo "- проект: $PROJECT, адрес: $URL"
        echo "- рабочая копия: $(git describe --tags --always --dirty 2> /dev/null || echo -)," \
             "ветка $(git branch --show-current 2> /dev/null || echo -)"
        echo
        echo '```'
        status
        echo '```'
    } | tee "$file"
    echo
    echo "Сохранено: $file"
}

case "${1:-status}" in
    status) status ;;
    alerts) alerts ;;
    targets) targets ;;
    query) query "${2:?укажите запрос PromQL}" | jq . ;;
    snapshot) snapshot "${2:-}" ;;
    -h | --help) awk 'NR > 1 && /^#/ {sub(/^# ?/, ""); print; next} NR > 1 {exit}' "$0" ;;
    *) echo "Неизвестная команда: $1 (scripts/obs.sh --help)" >&2; exit 1 ;;
esac
