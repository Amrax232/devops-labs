#!/usr/bin/env bash
# Ожидание готовности контейнерного окружения: используется в make up и
# make container-check.
#
# Готово, когда:
#   - все долгоживущие контейнеры запущены и их healthcheck в состоянии healthy;
#   - разовые контейнеры (restart: "no", например migrate) завершились с кодом 0.
# Контейнер в состоянии unhealthy, перезапускающийся или упавший — ошибка:
# выводятся его последние строки журнала.
#
# Переменные: WAIT_TIMEOUT (по умолчанию 180 с). Аргументы передаются
# docker compose (например, -p <проект>).
set -euo pipefail

cd "$(dirname "$0")/.."
TIMEOUT="${WAIT_TIMEOUT:-180}"
compose() { docker compose "$@"; }
COMPOSE_ARGS=("$@")

state_of() {
    docker inspect -f '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.State.ExitCode}} {{.HostConfig.RestartPolicy.Name}} {{.RestartCount}}' "$1"
}

die() {
    echo "ОШИБКА: $1" >&2
    docker logs --tail 30 "$2" >&2 2>&1 || true
    exit 1
}

deadline=$((SECONDS + TIMEOUT))
while :; do
    ids="$(compose "${COMPOSE_ARGS[@]}" ps -a -q)"
    [ -n "$ids" ] || { echo "ОШИБКА: контейнеров нет — выполните docker compose up -d" >&2; exit 1; }
    pending=()
    for id in $ids; do
        read -r name status health code restart restarts < <(state_of "$id")
        name="${name#/}"
        case "$status" in
            exited)
                if [ "$code" = "0" ] && { [ "$restart" = "no" ] || [ -z "$restart" ]; }; then
                    continue
                fi
                die "$name завершился с кодом $code" "$id" ;;
            restarting)
                die "$name перезапускается (падает при старте)" "$id" ;;
            running)
                if [ "$restarts" != "0" ] && [ "$health" != "healthy" ]; then
                    die "$name перезапускался $restarts раз" "$id"
                fi
                case "$health" in
                    healthy) continue ;;
                    unhealthy) die "$name: healthcheck — unhealthy" "$id" ;;
                    none) [ "$restart" = "no" ] || die "$name: нет healthcheck" "$id" ;;
                esac
                pending+=("$name:$health") ;;
            *)
                pending+=("$name:$status") ;;
        esac
    done
    if [ "${#pending[@]}" -eq 0 ]; then
        echo "Окружение готово: все сервисы healthy, разовые задачи завершены успешно."
        exit 0
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "ОШИБКА: за ${TIMEOUT} с не готовы: ${pending[*]}" >&2
        exit 1
    fi
    sleep 2
done
