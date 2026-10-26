#!/usr/bin/env bash
# Проверка работающего релиза: make smoke [URL=...] [REVISION=<commit SHA>]
#
# Выполняется после развёртывания (deploy/stage/deploy.sh) и в CI после
# make container-check — один и тот же сценарий в обоих местах:
#   1. служебные адреса: /healthz, /readyz (база доступна);
#   2. работающая версия: /version, коммит совпадает с выпуском;
#   3. разграничение доступа: изменение без входа отклоняется;
#   4. основной пользовательский сценарий: единица измерения, поставщик,
#      материал → поступление → проведение → остаток вырос → списание →
#      остаток уменьшился → списать больше остатка нельзя → отчёт.
# Любое расхождение — код 1: выпуск не считается успешным.
#
# Нужны curl и jq. Логин и пароль — AUTH_USERNAME / AUTH_PASSWORD из
# окружения (или из .env в каталоге проекта).
set -euo pipefail

BASE="${1:-http://127.0.0.1:${HTTP_PORT:-8080}}"
EXPECTED_REVISION="${2:-}"
if [ -z "${AUTH_PASSWORD:-}" ] && [ -f "$(dirname "$0")/../.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$(dirname "$0")/../.env"
    set +a
fi
AUTH="${AUTH_USERNAME:-admin}:${AUTH_PASSWORD:?нет AUTH_PASSWORD}"
for tool in curl jq; do
    command -v "$tool" > /dev/null || { echo "Нужна утилита $tool" >&2; exit 1; }
done

BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT
STEP=0

fail() { echo "  [FAIL] $*" >&2; exit 1; }
ok() { STEP=$((STEP + 1)); echo "  [OK] $*"; }

# call <метод> <путь> <ожидаемый код> [json] [--anonymous] → тело ответа в $BODY
call() {
    local method="$1" path="$2" expected="$3" data="${4:-}" anonymous="${5:-}" code
    local args=(-s -o "$BODY" -w '%{http_code}' --max-time 10 -X "$method")
    [ -n "$anonymous" ] || args+=(-u "$AUTH")
    [ -z "$data" ] || args+=(-H 'Content-Type: application/json' -d "$data")
    code="$(curl "${args[@]}" "$BASE$path")" || true    # нет соединения — curl выводит 000
    if [ "$code" != "$expected" ]; then
        fail "$method $path: код $code, ожидался $expected. Ответ: $(head -c 300 "$BODY")"
    fi
}
field() { jq -r "$1" "$BODY"; }

echo "Проверка релиза: $BASE"

# ------------------------------------------------------------- 1. служебные
call GET /healthz 200 "" anonymous
[ "$(field .status)" = ok ] || fail "/healthz: $(cat "$BODY")"
call GET /readyz 200 "" anonymous
[ "$(field .database)" = ok ] || fail "/readyz: $(cat "$BODY")"
ok "служебные адреса: /healthz — ok, /readyz — база доступна"

# --------------------------------------------------------------- 2. версия
call GET /version 200 "" anonymous
version="$(field .version)"
revision="$(field .revision)"
if [ -n "$EXPECTED_REVISION" ] && [ "$revision" != "$EXPECTED_REVISION" ]; then
    fail "работает не та версия: коммит $revision, ожидался $EXPECTED_REVISION"
fi
ok "работает версия $version, коммит $revision, экземпляр $(field .instance)"

# ---------------------------------------------------- 3. разграничение доступа
call POST /api/v1/units 401 '{"code":"anon","name":"Без входа"}' anonymous
ok "изменение без входа отклонено (401)"

# --------------------------------------------------------- 4. основной сценарий
stamp="$(date +%s)"            # 10 цифр: уникальный код и ИНН для каждого прогона
today="$(date +%F)"

call POST /api/v1/units 201 "{\"code\":\"s$stamp\",\"name\":\"Проверка релиза\"}"
unit_id="$(field .id)"
call POST /api/v1/suppliers 201 "{\"name\":\"Проверка релиза $stamp\",\"inn\":\"$stamp\"}"
supplier_id="$(field .id)"
call POST /api/v1/materials 201 \
    "{\"sku\":\"SMOKE-$stamp\",\"name\":\"Проверка релиза\",\"unit_id\":$unit_id,\"min_stock\":\"1\"}"
material_id="$(field .id)"
ok "справочники: единица $unit_id, поставщик $supplier_id, материал $material_id"

call POST /api/v1/receipts 201 "{\"number\":\"SMOKE-$stamp\",\"supplier_id\":$supplier_id,\
\"received_at\":\"$today\",\"items\":[{\"material_id\":$material_id,\"quantity\":\"5\",\"price\":\"10\"}]}"
receipt_id="$(field .id)"
call POST "/api/v1/receipts/$receipt_id/post" 200
[ "$(field .status)" = posted ] || fail "поступление не проведено: $(cat "$BODY")"
call GET "/api/v1/materials/$material_id" 200
[ "$(field '(.quantity | tonumber) == 5')" = true ] || fail "остаток после поступления: $(field .quantity)"
ok "поступление $receipt_id проведено, остаток 5"

call POST "/api/v1/materials/$material_id/write-offs" 201 '{"quantity":"2","reason":"Проверка релиза"}'
call GET "/api/v1/materials/$material_id" 200
[ "$(field '(.quantity | tonumber) == 3')" = true ] || fail "остаток после списания: $(field .quantity)"
call POST "/api/v1/materials/$material_id/write-offs" 422 '{"quantity":"100","reason":"Больше остатка"}'
ok "списание 2 → остаток 3; списать больше остатка нельзя (422)"

call GET /api/v1/reports/stock 200 "" anonymous
[ "$(field .positions)" -ge 1 ] || fail "отчёт по остаткам пуст"
ok "отчёт по остаткам: позиций $(field .positions)"

echo "Релиз работает: пройдено проверок — $STEP."
