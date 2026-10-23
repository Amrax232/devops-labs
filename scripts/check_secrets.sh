#!/usr/bin/env bash
# Секреты и рабочие данные не должны попадать в репозиторий: make secrets
set -euo pipefail
cd "$(dirname "$0")/.."

if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "Каталог не является git-репозиторием — проверка невозможна" >&2
    exit 1
fi

fail=0

# 1. Файлы, которых в репозитории быть не должно
forbidden=$(git ls-files | grep -E '(^|/)(\.env|\.env\.local|warehouse\.env)$|\.(pem|key|dump|sqlite3)$' || true)
if [ -n "$forbidden" ]; then
    echo "ОШИБКА: под контролем версий секреты или данные:"
    echo "$forbidden" | sed 's/^/  /'
    fail=1
fi

# 2. Закрытые ключи внутри любых файлов
keys=$(git grep -lE -- '-----BEGIN [A-Z ]*PRIVATE KEY-----' -- ':!scripts/check_secrets.sh' || true)
if [ -n "$keys" ]; then
    echo "ОШИБКА: в файлах найден закрытый ключ:"
    echo "$keys" | sed 's/^/  /'
    fail=1
fi

# 3. В шаблонах конфигурации вместо паролей — только заглушки
for template in .env.example deploy/app/warehouse.env.example; do
    [ -f "$template" ] || continue
    leaked=$(grep -nE '^(AUTH_PASSWORD|POSTGRES_PASSWORD)=' "$template" \
        | grep -vE '=(CHANGE_ME|warehouse|warehouse123)$' || true)
    if [ -n "$leaked" ]; then
        echo "ОШИБКА: в шаблоне $template похоже на реальный пароль:"
        echo "$leaked" | sed 's/^/  /'
        fail=1
    fi
done

if [ "$fail" -eq 0 ]; then
    echo "Секретов в репозитории не найдено."
fi
exit "$fail"
