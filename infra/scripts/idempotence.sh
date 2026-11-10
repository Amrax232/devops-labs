#!/usr/bin/env bash
# Проверка повторяемости: make infra-idempotence ENV=<окружение>
#
# Повторно применяет site.yml к уже настроенной машине. Требование: ни одной
# изменённой задачи (changed=0) и ни одной ошибки. Если что-то изменилось —
# выводится список таких задач: это либо дрейф, либо неидемпотентная задача.
# Аргументы передаются ansible-playbook (инвентарь, vault, ключ).
set -euo pipefail
cd "$(dirname "$0")/.."

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT
.venv/bin/ansible-playbook "$@" site.yml | tee "$LOG"

recap="$(sed -n '/^PLAY RECAP/,$p' "$LOG")"
changed_tasks="$(awk '/^TASK \[/ {task=$0} /^changed: / {print "  " task}' "$LOG" | sort -u)"
if grep -Eq 'changed=[1-9]|failed=[1-9]|unreachable=[1-9]' <<< "$recap"; then
    echo
    echo "ПОВТОРНЫЙ ЗАПУСК ИЗМЕНИЛ СОСТОЯНИЕ — конфигурация не идемпотентна:" >&2
    echo "${changed_tasks:-  (см. журнал выше)}" >&2
    exit 1
fi
echo
echo "Повторный запуск: changed=0 — состояние уже соответствует коду."
