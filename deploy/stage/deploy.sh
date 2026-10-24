#!/usr/bin/env bash
# Развёртывание в тестовое окружение (staging) — ЛР6.
#
#   deploy/stage/deploy.sh deploy <тег>    развернуть образ с тегом из реестра
#   deploy/stage/deploy.sh rollback        вернуть предыдущую успешную версию
#   deploy/stage/deploy.sh status          что работает сейчас, история выпусков
#
# Запускает задание CD на self-hosted runner сервера staging под отдельной
# учётной записью deploy (.github/workflows/deploy.yml); вручную — тем же
# пользователем из рабочей копии репозитория.
#
# Порядок выпуска:
#   1. блокировка: одновременно идёт только одно развёртывание (flock);
#   2. настройки окружения — файл на сервере, отдельно от образа: все
#      обязательные переменные должны быть заданы, иначе выпуск не начинается;
#   3. образ скачивается из реестра (не собирается); по метке образа
#      определяется коммит, из него берутся compose-файлы и nginx.conf;
#   4. копия базы перед выпуском;
#   5. переключение: docker compose up --no-build;
#   6. проверка выпуска: все контейнеры healthy и из нужного образа,
#      /healthz, /readyz, /version = коммит образа, основной сценарий
#      (scripts/smoke_test.sh);
#   7. успех — версия записывается как текущая. Провал — выпуск НЕ успешен
#      (код 1), автоматически возвращается предыдущая версия (AUTO_ROLLBACK).
#
# Ошибки до шага 5 (нет переменной, неверный тег, реестр недоступен) ничего
# не меняют: продолжает работать прежняя версия.
#
# Имитация сбоев для защиты: SIMULATE_FAILURE=healthcheck|scenario|registry|missing-var.
set -euo pipefail

ACTION="${1:-}"
TAG_ARG="${2:-}"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
STAGE_DIR="${STAGE_DIR:-/opt/warehouse-stage}"
ENV_FILE="${ENV_FILE:-$STAGE_DIR/env/stage.env}"
STATE="$STAGE_DIR/state"
RELEASES="$STAGE_DIR/releases"
BACKUPS="$STAGE_DIR/backups"
SIMULATE="${SIMULATE_FAILURE:-none}"
REQUIRED_VARS=(REGISTRY_IMAGE AUTH_USERNAME AUTH_PASSWORD
               POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB HTTP_BIND HTTP_PORT)
BUNDLE=(docker-compose.yml docker-compose.deploy.yml nginx deploy/stage
        scripts/compose_wait.sh scripts/smoke_test.sh)

log() { echo "[$(date '+%F %T')] $*"; }
die() { log "ОШИБКА: $*" >&2; record FAILED "${TAG:-$TAG_ARG}" "$*"; summary "НЕ ВЫПОЛНЕНО" "$*"; exit 1; }
record() {  # история выпусков: время, результат, тег, комментарий, запуск CI
    mkdir -p "$STATE"
    printf '%s\t%s\t%s\t%s\t%s\n' "$(date -Iseconds)" "$1" "${2:--}" "$3" \
        "${GITHUB_RUN_ID:-вручную}" >> "$STATE/history.tsv"
}
summary() {  # итог в Summary запуска GitHub Actions
    [ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
    {
        echo "## Развёртывание в staging: $1"
        echo
        echo "$2"
        echo
        echo "| | |"
        echo "|---|---|"
        echo "| Действие | \`$ACTION\` |"
        echo "| Тег | \`${TAG:-$TAG_ARG}\` |"
        echo "| Работает сейчас | \`$(cat "$STATE/current_tag" 2> /dev/null || echo —)\` |"
        echo "| Имитация сбоя | \`$SIMULATE\` |"
    } >> "$GITHUB_STEP_SUMMARY"
}

usage() { sed -n '2,9p' "$0"; exit 1; }
[ -n "$ACTION" ] || usage

# ------------------------------------------------------------- состояние
stack_top() { tail -n 1 "$STATE/stack" 2> /dev/null || true; }
stack_prev() { tail -n 2 "$STATE/stack" 2> /dev/null | head -n 1; }
stack_size() { [ -f "$STATE/stack" ] && wc -l < "$STATE/stack" || echo 0; }

status() {
    echo "Окружение: $STAGE_DIR (проект ${COMPOSE_PROJECT_NAME:-warehouse-stage})"
    echo "Текущая версия:    $(cat "$STATE/current_tag" 2> /dev/null || echo —)"
    echo "Коммит:            $(cat "$STATE/current_revision" 2> /dev/null || echo —)"
    echo "Предыдущая версия: $( [ "$(stack_size)" -ge 2 ] && stack_prev || echo —)"
    echo
    echo "Последние выпуски (время, результат, тег, комментарий, запуск):"
    tail -n 10 "$STATE/history.tsv" 2> /dev/null | sed 's/^/  /' || echo "  —"
}

# ------------------------------------------------------- 2. настройки окружения
load_env() {
    [ -f "$ENV_FILE" ] || die "нет файла настроек окружения $ENV_FILE (шаблон: deploy/stage/stage.env.example)"
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
    if [ "$SIMULATE" = missing-var ]; then
        log "ИМИТАЦИЯ: из окружения убрана переменная AUTH_PASSWORD"
        unset AUTH_PASSWORD
    fi
    if [ "$SIMULATE" = registry ]; then
        log "ИМИТАЦИЯ: реестр недоступен (адрес registry.invalid)"
        REGISTRY_IMAGE="registry.invalid/warehouse-inventory"
    fi
    local missing=()
    for var in "${REQUIRED_VARS[@]}"; do
        [ -n "${!var:-}" ] || missing+=("$var")
    done
    [ "${#missing[@]}" -eq 0 ] \
        || die "не заданы переменные окружения: ${missing[*]} (в $ENV_FILE). Выпуск не начат, работает прежняя версия"
    export COMPOSE_PROJECT_NAME="${STAGE_PROJECT:-warehouse-stage}"
}

# ------------------------------------------------------------- 3. образ
pull_image() {  # с повтором: кратковременный сбой сети не должен ронять выпуск
    local image="$1" attempt output
    for attempt in 1 2 3; do
        if output="$(docker pull --quiet "$image" 2>&1)"; then
            log "образ получен из реестра: $image"
            return 0
        fi
        log "попытка $attempt: $output"
        # тега нет — повторять бессмысленно; сбой сети или реестра — повторяем
        if grep -Eqi 'manifest unknown|not found' <<< "$output"; then
            die "в реестре нет образа $image (неверный тег). Выпуск не начат, работает прежняя версия"
        fi
        if grep -Eqi 'denied|unauthorized' <<< "$output"; then
            die "нет доступа к образу $image в реестре (вход в реестр). Выпуск не начат, работает прежняя версия"
        fi
        [ "$attempt" -lt 3 ] && sleep 5
    done
    die "реестр недоступен: не удалось получить образ $image. Выпуск не начат, работает прежняя версия"
}

prepare_release() {  # compose-файлы и nginx.conf — из того же коммита, что и образ
    local rev="$1" dir="$RELEASES/$1" tmp
    if [ -d "$dir" ]; then
        log "файлы выпуска уже есть: $dir"
        return 0
    fi
    git -C "$REPO_DIR" cat-file -e "$rev^{commit}" 2> /dev/null \
        || die "коммита $rev нет в рабочей копии $REPO_DIR (нужен checkout с fetch-depth: 0)"
    tmp="$(mktemp -d "$RELEASES/.tmp-XXXXXX")"
    git -C "$REPO_DIR" archive "$rev" "${BUNDLE[@]}" | tar -x -C "$tmp" \
        || { rm -rf "$tmp"; die "в коммите $rev нет файлов развёртывания (выпуск собран до ЛР6)"; }
    mv "$tmp" "$dir"
    log "файлы выпуска из коммита $rev: $dir"
}

# ------------------------------------------------------------- 4. копия БД
backup_db() {
    local file
    if ! docker compose ps --status running -q db 2> /dev/null | grep -q .; then
        log "база ещё не запущена — копия перед выпуском не нужна"
        return 0
    fi
    mkdir -p "$BACKUPS"
    file="$BACKUPS/pre-deploy-$(date +%Y%m%d-%H%M%S)-$1.dump"
    docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --format=custom --no-owner > "$file.partial"
    mv "$file.partial" "$file"
    log "копия базы перед выпуском: $file ($(du -h "$file" | cut -f1))"
    # хранятся 5 последних копий
    ls -1t "$BACKUPS"/pre-deploy-*.dump 2> /dev/null | tail -n +6 | xargs -r rm -f
}

# ------------------------------------------------------ 5–6. переключение и проверка
switch_and_verify() {  # <тег> <коммит> <deploy|rollback> <имитация>
    local tag="$1" rev="$2" mode="$3" fault="$4" dir="$RELEASES/$2" files svc image url
    files="$dir/docker-compose.yml:$dir/docker-compose.deploy.yml"
    [ "$mode" = rollback ] && files+=":$dir/deploy/stage/rollback.yml"
    case "$fault" in
        healthcheck | scenario)
            log "ИМИТАЦИЯ: сбой «$fault» в новом выпуске"
            files+=":$REPO_DIR/deploy/stage/faults/$fault.yml" ;;
    esac
    export COMPOSE_FILE="$files" IMAGE_TAG="$tag"
    image="$REGISTRY_IMAGE:$tag"

    log "переключение на $image"
    docker compose up -d --no-build --remove-orphans 2>&1 | sed 's/^/    /' || return 1

    log "проверка контейнеров"
    WAIT_TIMEOUT="${WAIT_TIMEOUT:-180}" "$dir/scripts/compose_wait.sh" 2>&1 | sed 's/^/    /' || return 1
    for svc in app1 app2; do
        [ "$(docker inspect -f '{{.Config.Image}}' "$(docker compose ps -q "$svc")")" = "$image" ] \
            || { log "$svc запущен не из $image"; return 1; }
    done
    log "    app1, app2 работают из $image"

    url="http://${HTTP_BIND/0.0.0.0/127.0.0.1}:$HTTP_PORT"
    log "проверка выпуска: служебные адреса, версия, основной сценарий ($url)"
    "$dir/scripts/smoke_test.sh" "$url" "$rev" 2>&1 | sed 's/^/    /' || return 1
}

release() {  # <тег> <deploy|rollback>
    local tag="$1" mode="$2" rev previous_tag previous_rev
    TAG="$tag"
    [[ "$tag" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] || die "недопустимый тег «$tag»"
    [ "$tag" != latest ] || die "тег latest запрещён: по нему не видно, что развёрнуто"

    pull_image "$REGISTRY_IMAGE:$tag"
    rev="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
        "$REGISTRY_IMAGE:$tag")"
    [[ "$rev" =~ ^[0-9a-f]{40}$ ]] || die "у образа нет метки коммита (revision: «$rev»)"
    log "коммит образа: $rev"
    prepare_release "$rev"

    previous_tag="$(stack_top)"
    previous_rev="$(cat "$STATE/current_revision" 2> /dev/null || true)"
    export COMPOSE_FILE="$RELEASES/$rev/docker-compose.yml:$RELEASES/$rev/docker-compose.deploy.yml"
    export IMAGE_TAG="$tag"
    [ "$mode" = rollback ] || backup_db "$tag"

    local fault=none
    [ "$mode" = deploy ] && fault="$SIMULATE"
    if switch_and_verify "$tag" "$rev" "$mode" "$fault"; then
        if [ "$mode" = rollback ]; then
            sed -i '$d' "$STATE/stack"             # снять неудачную версию со стека
        elif [ "$tag" != "$previous_tag" ]; then
            echo "$tag" >> "$STATE/stack"
        fi
        echo "$tag" > "$STATE/current_tag"
        echo "$rev" > "$STATE/current_revision"
        ln -sfn "$RELEASES/$rev" "$STAGE_DIR/current"
        record OK "$tag" "$mode: коммит $rev"
        log "ВЫПУСК УСПЕШЕН: работает $tag (коммит $rev)"
        summary "УСПЕШНО" "Работает \`$tag\`, коммит \`$rev\`. Все проверки после развёртывания пройдены."
        return 0
    fi

    log "ПРОВЕРКА ПОСЛЕ РАЗВЁРТЫВАНИЯ НЕ ПРОЙДЕНА: выпуск $tag не принят"
    docker compose ps -a 2>&1 | sed 's/^/    /' || true
    record FAILED "$tag" "$mode: проверка после развёртывания не пройдена"
    if [ "$mode" = deploy ] && [ "${AUTO_ROLLBACK:-1}" = 1 ] && [ -n "$previous_tag" ]; then
        log "возврат предыдущей версии $previous_tag"
        if switch_and_verify "$previous_tag" "$previous_rev" rollback none; then
            record OK "$previous_tag" "автоматический возврат после неудачи $tag"
            log "работает предыдущая версия $previous_tag"
            summary "НЕ ПРИНЯТ, возвращена предыдущая версия" \
                "Проверка \`$tag\` не пройдена. Работает \`$previous_tag\` — проверки пройдены."
        else
            record FAILED "$previous_tag" "автоматический возврат не удался"
            summary "НЕ ПРИНЯТ, возврат не удался" "Нужен ручной разбор: deploy.sh status"
        fi
    else
        summary "НЕ ПРИНЯТ" "Проверка \`$tag\` не пройдена, автоматический возврат не выполнялся."
    fi
    exit 1
}

# ------------------------------------------------------------------- запуск
mkdir -p "$STATE" "$RELEASES" "$BACKUPS"
[ "$ACTION" = status ] && { status; exit 0; }

# 1. одно развёртывание за раз (вместе с concurrency в deploy.yml)
exec 9> "$STAGE_DIR/deploy.lock"
if ! flock -w "${LOCK_TIMEOUT:-600}" 9; then
    die "идёт другое развёртывание (блокировка $STAGE_DIR/deploy.lock)"
fi
echo "$$ ${GITHUB_RUN_ID:-вручную} $ACTION $TAG_ARG" >&9

load_env
case "$ACTION" in
    deploy)
        [ -n "$TAG_ARG" ] || die "укажите тег: deploy.sh deploy <тег>"
        release "$TAG_ARG" deploy ;;
    rollback)
        [ "$(stack_size)" -ge 2 ] || die "нет предыдущей успешной версии для возврата"
        log "возврат: $(stack_top) → $(stack_prev)"
        release "$(stack_prev)" rollback ;;
    *) usage ;;
esac
