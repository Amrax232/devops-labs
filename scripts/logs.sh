#!/usr/bin/env bash
# Поиск по структурированным журналам (ЛР8): make logs-find ...
#
# Журналы — строки JSON в docker logs (приложение, Nginx, Grafana). Скрипт
# собирает их из контейнеров проекта, отбирает по полям и выводит таблицей:
#
#   scripts/logs.sh -i <request_id>          путь одного запроса: Nginx → экземпляр
#   scripts/logs.sh -l ERROR -t 30m          ошибки за 30 минут
#   scripts/logs.sh -e http_request -c 5     ответы 5xx (код начинается с 5)
#   scripts/logs.sh -e auth_failed           отказы в доступе
#   scripts/logs.sh -q "База данных"         поиск по тексту сообщения
#   scripts/logs.sh --json ...               исходные записи JSON (для jq)
#   scripts/logs.sh --check                  все записи приложения — JSON с
#                                            обязательными полями (make container-check)
#   scripts/logs.sh --secrets                в журналах нет настоящих значений
#                                            паролей из .env (make logs-secrets)
#
# Параметры: -s сервисы через запятую (по умолчанию app1,app2,nginx),
# -t период (docker logs --since: 15m, 2h, 2026-11-05T10:00:00), -n не больше N
# записей. PROJECT — имя проекта compose: warehouse-inventory (локально),
# warehouse-stage, warehouse-prod; ENV_FILE — файл с паролями для --secrets.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${PROJECT:-warehouse-inventory}"
ENV_FILE="${ENV_FILE:-.env}"
SERVICES="app1,app2,nginx"
SINCE="1h"
REQUEST_ID="" LEVEL="" EVENT="" STATUS="" TEXT="" LIMIT=200 MODE=table

usage() { awk 'NR > 1 && /^#/ {sub(/^# ?/, ""); print; next} NR > 1 {exit}' "$0"; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
    case "$1" in
        -s) SERVICES="$2"; shift ;;
        -t) SINCE="$2"; shift ;;
        -i) REQUEST_ID="$2"; shift ;;
        -l) LEVEL="${2^^}"; shift ;;
        -e) EVENT="$2"; shift ;;
        -c) STATUS="$2"; shift ;;
        -q) TEXT="$2"; shift ;;
        -n) LIMIT="$2"; shift ;;
        --json) MODE=json ;;
        --check) MODE=check ;;
        --secrets) MODE=secrets; SERVICES="app1,app2,nginx,db,grafana,prometheus" ;;
        -h | --help) usage ;;
        *) echo "Неизвестный параметр: $1" >&2; usage 1 ;;
    esac
    shift
done
command -v jq > /dev/null || { echo "Нужен jq: sudo apt-get install -y jq" >&2; exit 1; }

# записи всех выбранных сервисов: к каждой строке добавляется имя сервиса
collect() {
    local svc container
    IFS=, read -ra list <<< "$SERVICES"
    for svc in "${list[@]}"; do
        container="$PROJECT-$svc-1"
        if ! docker inspect "$container" > /dev/null 2>&1; then
            echo "нет контейнера $container (PROJECT=$PROJECT)" >&2
            continue
        fi
        docker logs --since "$SINCE" "$container" 2>&1 | sed "s/^/$svc\t/"
    done
}

# --------------------------------------------- журналы приложения — JSON с полями
if [ "$MODE" = check ]; then
    SERVICES="app1,app2"
    lines="$(collect)"
    [ -n "$lines" ] || { echo "ОШИБКА: журналы приложения пусты" >&2; exit 1; }
    bad="$(cut -f2- <<< "$lines" | jq -Rr '
        (fromjson? // null) as $e
        | if $e == null then "не JSON: \(.[0:120])"
          else ([ "time", "level", "event", "message", "request_id", "instance" ]
                - ($e | keys)) as $missing
          | if ($missing | length) > 0 then "нет полей \($missing | join(",")): \(.[0:120])"
            elif $e.event == "http_request"
                 and ([ "method", "endpoint", "status", "result", "duration_ms" ] - ($e | keys) | length) > 0
            then "запрос без method/endpoint/status/result/duration_ms: \(.[0:120])"
            else empty end
          end')"
    total="$(wc -l <<< "$lines")"
    if [ -n "$bad" ]; then
        echo "ОШИБКА: записи журнала не соответствуют формату (docs/observability.md):" >&2
        head -10 <<< "$bad" >&2
        exit 1
    fi
    echo "журналы app1, app2: $total записей, все — JSON с обязательными полями"
    exit 0
fi

# ------------------------------------------- настоящие пароли в журналах (утечка)
if [ "$MODE" = secrets ]; then
    [ -f "$ENV_FILE" ] || { echo "Нет $ENV_FILE с паролями окружения" >&2; exit 1; }
    mapfile -t secrets < <(grep -E '^(AUTH_PASSWORD|POSTGRES_PASSWORD|GRAFANA_ADMIN_PASSWORD)=' "$ENV_FILE" \
        | cut -d= -f2- | awk 'length($0) >= 6')
    [ "${#secrets[@]}" -gt 0 ] || { echo "В $ENV_FILE нет паролей для проверки" >&2; exit 1; }
    lines="$(collect)"
    found=0
    for secret in "${secrets[@]}"; do
        if hits="$(grep -F -- "$secret" <<< "$lines")"; then
            found=1
            # сам пароль не выводится: только сервис и номер строки
            cut -f1 <<< "$hits" | sort | uniq -c | while read -r count where; do
                echo "УТЕЧКА: пароль из $ENV_FILE найден в журнале ($where: $count строк)" >&2
            done
        fi
    done
    patterns='(password|passwd|secret|token)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?[^*"'"'"'[:space:],;}]{4,}|Authorization:[[:space:]]*(Basic|Bearer)[[:space:]]+[^*[:space:]]|://[^:/@[:space:]]+:[^*@/[:space:]]+@|gh[pousr]_[A-Za-z0-9]{36,}'
    # типичные формы секретов — только в журналах своего кода (приложение, Nginx)
    if hits="$(grep -E $'^(app1|app2|nginx)\t' <<< "$lines" | grep -Ei -- "$patterns" \
            | cut -f1 | sort | uniq -c)" && [ -n "$hits" ]; then
        found=1
        while read -r count where; do
            echo "ПОДОЗРЕНИЕ: похожее на секрет значение в журнале $where ($count строк):" \
                 "scripts/logs.sh -s $where --json | grep -Ei 'password|token|secret'" >&2
        done <<< "$hits"
    fi
    [ "$found" = 0 ] || exit 1
    echo "журналы ${SERVICES//,/, } за $SINCE: открытых паролей и секретов нет"
    exit 0
fi

# ------------------------------------------------------------------- поиск
collect | jq -Rr --arg id "$REQUEST_ID" --arg level "$LEVEL" --arg event "$EVENT" \
    --arg status "$STATUS" --arg text "$TEXT" --arg mode "$MODE" '
    (split("\t")) as [$svc, $line]
    | ($line | fromjson? // {level: "RAW", event: "-", message: $line}) as $e
    | select($id == "" or $e.request_id == $id)
    | select($level == "" or $e.level == $level)
    | select($event == "" or $e.event == $event)
    | select($status == "" or (($e.status // "") | tostring | startswith($status)))
    | select($text == "" or ($e.message // "" | ascii_downcase | contains($text | ascii_downcase)))
    | if $mode == "json" then ($e + {service: $svc} | tojson)
      else [ ($e.time // "-" | tostring | sub("[+]00:00$"; "") | .[0:23]), $svc, ($e.level // "-"), ($e.event // "-"),
             ($e.method // ""), ($e.endpoint // $e.path // ""), ($e.status // "" | tostring),
             (if $e.duration_ms then "\($e.duration_ms)"
              elif $e.duration_s then "\($e.duration_s * 1000 | round)" else "" end),
             ($e.request_id // "-"), ($e.message // "") ] | @tsv
      end' \
    | sort | tail -n "$LIMIT" \
    | if [ "$MODE" = json ]; then cat; else
        { printf 'время\tсервис\tуровень\tсобытие\tметод\tадрес\tкод\tмс\trequest_id\tсообщение\n'; cat; } \
            | if command -v column > /dev/null; then column -t -s $'\t'; else cat; fi
      fi
