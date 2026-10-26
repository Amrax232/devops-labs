#!/usr/bin/env bash
# Полная проверка контейнерного окружения: make container-check
#
# Изменение Dockerfile, docker-compose*.yml или nginx/nginx.conf принимается
# только после успешного выполнения этой проверки (docs/workflow.md).
#
#   1. статические запреты (scripts/check_containers.py);
#   2. сборка образа;
#   3. запуск и готовность: healthcheck всех сервисов, миграции завершены;
#   4. процессы не от root, корневая ФС только на чтение, ограничения ресурсов;
#   5. сети: наружу открыт только nginx, БД и приложение без выхода наружу;
#   6. секретов в образе нет;
#   7. работа через nginx и разграничение доступа;
#   8. балансировка между экземплярами;
#   9. отказ экземпляра: сервис остаётся доступен;
#  10. штатная остановка по SIGTERM;
#  11. сохранность данных после пересоздания контейнеров и обновления образа;
#  12. миграции в контейнерной среде;
#  13. резервная копия и восстановление в новый том;
#  14. ограничение частоты запросов.
#
# Проверка пересоздаёт контейнеры (данные в томе сохраняются) и в конце
# возвращает окружение в рабочее состояние.
set -euo pipefail

cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
    echo "Нет файла .env: выполните cp .env.example .env" >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a

PYTHON="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PYTHON=.venv/bin/python
HTTP_PORT="${HTTP_PORT:-8080}"
BASE="http://127.0.0.1:${HTTP_PORT}"
AUTH="${AUTH_USERNAME:-admin}:${AUTH_PASSWORD:?задайте AUTH_PASSWORD в .env}"
VERSION="${APP_VERSION:-0.8.0}"
IMAGE="warehouse-inventory:${VERSION}"
PROJECT="warehouse-inventory"
TOTAL=14
CHECKS=0
TEST_UNIT_ID=""
UPDATE_TAG="${VERSION}-update-check"

step() { echo; echo "==> $1/${TOTAL} $2"; }
ok() { CHECKS=$((CHECKS + 1)); echo "    [OK] $*"; }
info() { echo "         $*"; }
fail() { echo "    [FAIL] $*" >&2; exit 1; }

cid() { docker compose ps -q "$1"; }

# HTTP-запрос через nginx: печатает «код экземпляр»
probe() {
    local path="${1:-/healthz}" headers code instance
    headers="$(curl -s -o /dev/null -D - --max-time 5 "$BASE$path" | tr -d '\r')" || true
    code="$(echo "$headers" | awk 'NR == 1 {print $2}')"
    instance="$(echo "$headers" | awk -F': ' 'tolower($1) == "x-instance-id" {print $2}')"
    echo "${code:-000} ${instance:--}"
}

series() {  # n запросов подряд → строки «код экземпляр»
    local n="$1" _
    for _ in $(seq 1 "$n"); do probe /healthz; done
}

wait_instance_back() {  # ждём, пока nginx снова начнёт отправлять запросы на экземпляр
    local instance="$1" _
    for _ in $(seq 1 30); do
        # вывод сначала целиком: с pipefail «series | grep -q» ложно падает по SIGPIPE
        [[ "$(series 4)" == *" $instance"* ]] && return 0
        sleep 1
    done
    return 1
}

on_exit() {
    local code=$?
    if [ -n "$TEST_UNIT_ID" ]; then
        curl -s -o /dev/null -u "$AUTH" -X DELETE "$BASE/api/v1/units/$TEST_UNIT_ID" || true
    fi
    if [ "$code" -ne 0 ]; then
        echo >&2
        echo "Проверка не пройдена. Состояние контейнеров:" >&2
        docker compose ps -a >&2 || true
        echo "Возврат остановленных сервисов: docker compose up -d" >&2
        docker compose up -d > /dev/null 2>&1 || true
    fi
    exit "$code"
}
trap on_exit EXIT

command -v curl > /dev/null || fail "нужна утилита curl: sudo apt install curl"
docker info > /dev/null 2>&1 || fail "Docker недоступен: запустите Docker Desktop / службу docker"
echo "Docker $(docker version -f '{{.Server.Version}}'), $(docker compose version)"

# ------------------------------------------------------------------------- 1
step 1 "статические запреты: latest, root, секреты, healthcheck, порты"
"$PYTHON" scripts/check_containers.py | sed 's/^/    /'
ok "Dockerfile, .dockerignore и compose соответствуют требованиям"

# ------------------------------------------------------------------------- 2
step 2 "сборка образа $IMAGE"
docker compose build --quiet
size="$(docker image inspect -f '{{.Size}}' "$IMAGE")"
ok "образ собран: $IMAGE, $((size / 1024 / 1024)) МБ"
info "базовые образы: $(grep -E '^ARG PYTHON_IMAGE' Dockerfile | cut -d= -f2)," \
     "$(docker compose config --images | grep -v warehouse-inventory | sort -u | xargs)"
info "пользователь образа: $(docker image inspect -f '{{.Config.User}}' "$IMAGE")"

# ------------------------------------------------------------------------- 3
step 3 "запуск: db → migrate → app1, app2 → nginx"
docker compose up -d --remove-orphans 2>&1 | sed 's/^/    /'
./scripts/compose_wait.sh | sed 's/^/    /'
migrate_id="$(docker compose ps -a -q migrate)"
[ "$(docker inspect -f '{{.State.ExitCode}}' "$migrate_id")" = "0" ] || fail "миграции завершились с ошибкой"
ok "миграции применены (migrate завершился с кодом 0)"
for svc in db app1 app2 nginx; do
    health="$(docker inspect -f '{{.State.Health.Status}}' "$(cid "$svc")")"
    [ "$health" = "healthy" ] || fail "$svc: $health"
done
ok "healthcheck: db, app1, app2, nginx — healthy"

# ------------------------------------------------------------------------- 4
step 4 "процессы не от root, ФС только на чтение, ограничения ресурсов"
for svc in db app1 app2 nginx; do
    # первый столбец docker top — владелец процесса (имя берётся из /etc/passwd
    # хоста, поэтому uid 101 или 70 может отображаться под другим именем)
    users="$(docker top "$(cid "$svc")" | awk 'NR > 1 {print $1}' | sort -u | xargs)"
    case " $users " in
        *" root "* | *" 0 "*) fail "$svc: есть процессы от root ($users)" ;;
    esac
    info "$svc: владельцы процессов — $users (пользователь запуска: $(docker inspect -f \
        '{{.Config.User}}' "$(cid "$svc")" | sed 's/^$/root, entrypoint понижает права до postgres/'))"
done
ok "ни один процесс в контейнерах не работает от root"
[ "$(docker compose exec -T app1 id -u)" = "10001" ] || fail "app1 запущен не от uid 10001"
if docker compose exec -T app1 sh -c 'touch /app/probe' 2> /dev/null; then
    fail "в app1 корневая ФС доступна на запись"
fi
docker compose exec -T app1 sh -c 'touch /tmp/probe && rm /tmp/probe' || fail "/tmp недоступен"
ok "app1: корневая ФС только на чтение, временные файлы — в tmpfs /tmp"
for svc in db app1 app2 nginx; do
    read -r mem cpu pids < <(docker inspect -f \
        '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}' "$(cid "$svc")")
    [ "$mem" -gt 0 ] && [ "$cpu" -gt 0 ] && [ "${pids:-0}" -gt 0 ] || fail "$svc: нет ограничений"
    info "$svc: память $((mem / 1024 / 1024)) МБ, CPU $(awk "BEGIN {print $cpu / 1e9}"), процессов $pids"
done
ok "ограничения памяти, CPU и числа процессов заданы для всех сервисов"
info "фактическое потребление:"
# shellcheck disable=SC2046 # список идентификаторов контейнеров — отдельные аргументы
docker stats --no-stream --format '{{.Name}}: {{.MemUsage}}, CPU {{.CPUPerc}}' \
    $(docker compose ps -q) | sed 's/^/           /'

# ------------------------------------------------------------------------- 5
step 5 "сети и порты"
for svc in db app1 app2; do
    published="$(docker port "$(cid "$svc")" 2> /dev/null || true)"
    [ -z "$published" ] || fail "$svc публикует порт: $published"
done
ok "у db, app1, app2 опубликованных портов нет"
info "nginx: $(docker port "$(cid nginx)" | xargs)"
for net in app_net db_net; do
    [ "$(docker network inspect -f '{{.Internal}}' "${PROJECT}_${net}")" = "true" ] \
        || fail "сеть $net не внутренняя"
done
ok "сети app_net и db_net внутренние (internal: true)"
if docker compose exec -T app1 python -c \
    "import socket; socket.create_connection(('1.1.1.1', 53), timeout=2)" 2> /dev/null; then
    fail "из app1 доступна внешняя сеть"
fi
ok "из контейнера приложения нет выхода во внешнюю сеть"

# ------------------------------------------------------------------------- 6
step 6 "секретов в образе нет"
image_env="$(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$IMAGE")"
if echo "$image_env" | grep -Eiq '^[A-Z_]*(PASSWORD|SECRET|TOKEN|DATABASE_URL)='; then
    fail "в переменных образа есть секреты"
fi
history="$(docker history --no-trunc --format '{{.CreatedBy}}' "$IMAGE")"
if echo "$history" | grep -Eiq 'PASSWORD|SECRET|TOKEN'; then
    fail "в истории слоёв образа упоминаются пароли или ключи"
fi
# значение пароля как отдельное значение (после «=», «:» или пробела)
contains_value() {
    awk -v s="$1" '{
        line = $0
        while ((i = index(line, s)) > 0) {
            before = (i > 1) ? substr(line, i - 1, 1) : " "
            after = substr(line, i + length(s), 1)
            if (before ~ /[=: "]/ && after !~ /[A-Za-z0-9_-]/) found = 1
            line = substr(line, i + length(s))
        }
    } END { exit !found }'
}
for secret in "${AUTH_PASSWORD}" "${POSTGRES_PASSWORD:-warehouse}"; do
    if printf '%s\n%s\n' "$history" "$image_env" | contains_value "$secret"; then
        fail "значение пароля найдено в слоях образа"
    fi
done
docker run --rm --network none --entrypoint sh "$IMAGE" -c \
    'test ! -e /app/.env && test ! -e /app/.git && test ! -e /app/backups && test ! -e /app/tests' \
    || fail "в образ попали .env, .git, backups или tests"
ok "в ENV и истории слоёв образа паролей нет; .env, .git, backups, tests в образ не попали"
info "логин, пароль и DATABASE_URL передаются контейнерам при запуске (из .env)"

# ------------------------------------------------------------------------- 7
step 7 "работа через nginx и разграничение доступа"
read -r code _ < <(probe /healthz)
[ "$code" = "200" ] || fail "GET /healthz через nginx: $code"
read -r code _ < <(probe /api/v1/units)
[ "$code" = "200" ] || fail "GET /api/v1/units через nginx: $code"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
    -d '{"code":"x","name":"x"}' "$BASE/api/v1/units")"
[ "$code" = "401" ] || fail "POST без входа: $code (ожидалось 401)"
ok "через nginx: чтение — 200, изменение без входа — 401"
info "заголовки ответа: $(curl -s -D - -o /dev/null "$BASE/healthz" | tr -d '\r' \
    | grep -Ei '^(x-instance-id|x-upstream|server):' | xargs)"

# ------------------------------------------------------------------------- 8
step 8 "балансировка нагрузки"
dist="$(series 10 | awk '{print $2}' | sort | uniq -c | xargs)"
info "10 запросов распределились: $dist"
[[ "$dist" == *app-1* && "$dist" == *app-2* ]] || fail "запросы не распределяются между экземплярами"
ok "запросы обрабатывают оба экземпляра (app-1 и app-2)"

# ------------------------------------------------------------------------- 9
step 9 "отказ экземпляра: остановка app1"
docker compose kill -s SIGKILL app1 > /dev/null 2>&1
info "app1 аварийно остановлен (SIGKILL)"
results="$(series 10)"
bad="$(echo "$results" | awk '$1 != 200' | wc -l)"
dist="$(echo "$results" | awk '{print $2}' | sort | uniq -c | xargs)"
info "10 запросов при упавшем app1: $dist, ошибок: $bad"
[ "$bad" -eq 0 ] || fail "при отказе app1 пользователь получил ошибки"
ok "сервис доступен: nginx исключил app1 и повторил запросы на app2"
docker compose start app1 > /dev/null 2>&1
./scripts/compose_wait.sh > /dev/null
wait_instance_back app-1 || fail "app1 не вернулся в балансировку"
ok "app1 перезапущен и вернулся в балансировку"

# ------------------------------------------------------------------------ 10
step 10 "штатная остановка по SIGTERM (docker stop app2)"
started=$SECONDS
docker compose stop app2 > /dev/null 2>&1
elapsed=$((SECONDS - started))
app2_id="$(docker compose ps -a -q app2)"
exit_code="$(docker inspect -f '{{.State.ExitCode}}' "$app2_id")"
logs="$(docker logs --tail 20 "$app2_id" 2>&1)"
echo "$logs" | grep -E 'Shutting down|shutdown|остановлен|Finished server' \
    | sed 's/^/           /' || true
# 0 или 143 — процесс завершился сам после обработки SIGTERM (uvicorn после
# штатной остановки повторно поднимает сигнал); 137 — убит SIGKILL по таймауту.
case "$exit_code" in
    0 | 143) ;;
    *) fail "код завершения $exit_code (137 — не уложился в stop_grace_period и убит)" ;;
esac
echo "$logs" | grep -q "Application shutdown complete" || fail "нет штатного завершения uvicorn"
echo "$logs" | grep -q "остановлен: соединения с БД закрыты" || fail "нет сообщения о закрытии соединений"
ok "app2 завершился сам за ${elapsed} с, код $exit_code (лимит stop_grace_period — 20 с)"
read -r code _ < <(probe /healthz)
[ "$code" = "200" ] || fail "во время остановки app2 сервис недоступен"
ok "во время остановки app2 запросы обслуживает app1"
docker compose start app2 > /dev/null 2>&1
./scripts/compose_wait.sh > /dev/null
wait_instance_back app-2 || fail "app2 не вернулся в балансировку"

# ------------------------------------------------------------------------ 11
step 11 "сохранность данных после пересоздания контейнеров и обновления образа"
marker="ck$(date +%s)"
response="$(curl -s -u "$AUTH" -H 'Content-Type: application/json' \
    -d "{\"code\":\"$marker\",\"name\":\"Проверка сохранности\"}" "$BASE/api/v1/units")"
TEST_UNIT_ID="$(echo "$response" | sed -n 's/.*"id":\([0-9]*\).*/\1/p')"
[ -n "$TEST_UNIT_ID" ] || fail "не удалось создать запись: $response"
info "создана запись: единица измерения $marker (id $TEST_UNIT_ID)"
has_marker() { [[ "$(curl -s "$BASE/api/v1/units")" == *"\"$marker\""* ]]; }

docker compose down > /dev/null 2>&1
[ -z "$(docker compose ps -a -q)" ] || fail "контейнеры не удалены"
docker volume inspect "${PROJECT}_db_data" > /dev/null || fail "том db_data удалён"
info "docker compose down: контейнеры и сети удалены, том ${PROJECT}_db_data на месте"
docker compose up -d > /dev/null 2>&1
./scripts/compose_wait.sh > /dev/null
has_marker || fail "после пересоздания контейнеров запись пропала"
ok "после down/up запись на месте"

APP_VERSION="$UPDATE_TAG" docker compose build --quiet
APP_VERSION="$UPDATE_TAG" docker compose up -d --force-recreate > /dev/null 2>&1
APP_VERSION="$UPDATE_TAG" ./scripts/compose_wait.sh > /dev/null
running_image="$(docker inspect -f '{{.Config.Image}}' "$(cid app1)")"
[ "$running_image" = "warehouse-inventory:$UPDATE_TAG" ] || fail "образ не обновился: $running_image"
has_marker || fail "после обновления образа запись пропала"
ok "после обновления образа ($running_image) запись на месте"

docker compose up -d > /dev/null 2>&1
./scripts/compose_wait.sh > /dev/null
docker image rm "warehouse-inventory:$UPDATE_TAG" > /dev/null 2>&1 || true
curl -s -o /dev/null -u "$AUTH" -X DELETE "$BASE/api/v1/units/$TEST_UNIT_ID"
TEST_UNIT_ID=""
info "окружение возвращено на образ $IMAGE, проверочная запись удалена"

# ------------------------------------------------------------------------ 12
step 12 "миграции в контейнерной среде"
current="$(docker compose run --rm --no-deps -T migrate alembic current 2> /dev/null | tail -1)"
info "alembic current: $current"
[[ "$current" == *"(head)"* ]] || fail "база не на последней версии схемы"
ok "схема БД на последней версии (миграции выполняет контейнер migrate)"

# ------------------------------------------------------------------------ 13
step 13 "резервная копия и восстановление в новый том"
if [ "$(docker compose exec -T db psql -U "${POSTGRES_USER:-warehouse}" -d "${POSTGRES_DB:-warehouse}" \
        -tAc 'SELECT count(*) FROM materials')" = "0" ]; then
    info "база пуста — заполняю демонстрационными данными"
    docker compose exec -T app1 python -m scripts.seed > /dev/null
fi
./scripts/restore_new_volume.sh | sed 's/^/    /'
ok "копия восстановлена в новый том, данные совпали; рабочий том не затронут"

# ------------------------------------------------------------------------ 14
step 14 "ограничение частоты запросов (20 запросов/с, всплеск до 40)"
codes="$(seq 1 80 | xargs -P 40 -I{} curl -s -o /dev/null -w '%{http_code}\n' "$BASE/healthz" \
    | sort | uniq -c | xargs)"
info "80 одновременных запросов: $codes"
[[ "$codes" == *" 429"* ]] || fail "ограничение частоты не срабатывает"
[[ "$codes" == *" 200"* ]] || fail "все запросы отклонены"
ok "сверх лимита nginx отвечает 429, остальные запросы обслуживаются"
sleep 2

echo
echo "container-check: все проверки пройдены ($CHECKS)."
docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
