#!/usr/bin/env bash
# Владельцы конфигурации наблюдаемости в .github/CODEOWNERS (ЛР8).
#
# Правила оповещений, сбор метрик, панели и маскирование секретов в журналах
# меняются только с одобрением владельцев — тех же, что у Makefile:
#   /monitoring/            Prometheus, правила и их тесты, Grafana, blackbox
#   /app/logging_setup.py   маскирование секретов в журнале
#   /app/metrics.py         метрики, на которые опираются оповещения
# make policy проверяет, что у этих файлов есть владельцы.
# Изменённый CODEOWNERS закоммитьте через merge request.
set -euo pipefail
cd "$(dirname "$0")/.."

FILE=.github/CODEOWNERS
owners="$(awk '$1 == "/Makefile" {$1 = ""; print substr($0, 2)}' "$FILE")"
[ -n "$owners" ] || { echo "В $FILE нет владельцев /Makefile: scripts/setup_github.sh" >&2; exit 1; }
[[ "$owners" != *CHANGE_ME* ]] || { echo "В $FILE заглушки: scripts/setup_github.sh" >&2; exit 1; }

added=()
for path in /monitoring/ /app/logging_setup.py /app/metrics.py; do
    if grep -q "^${path//./\\.}[[:space:]]" "$FILE"; then
        echo "    уже есть: $(grep "^${path//./\\.}[[:space:]]" "$FILE")"
        continue
    fi
    [ "${#added[@]}" -gt 0 ] || printf '\n# Наблюдаемость (ЛР8): оповещения, метрики, маскирование секретов\n' >> "$FILE"
    printf '%-29s %s\n' "$path" "$owners" >> "$FILE"
    added+=("$path")
done
[ "${#added[@]}" -eq 0 ] || echo "    добавлено: ${added[*]} → $owners"
