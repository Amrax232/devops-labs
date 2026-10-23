#!/usr/bin/env bash
# Демонстрация защиты CI на защите ЛР5: ./scripts/ci_demo.sh <сценарий>
#
# Создаёт от текущего main ветку demo/<сценарий> с намеренно дефектным
# изменением и коммитом. Дальше: git push -u origin demo/<сценарий> и
# merge request в main — pipeline должен остановиться, образ не публикуется,
# влить изменение нельзя. После показа ветку удаляют, в main она не попадает.
#
# Сценарии:
#   ok              корректное изменение (документация) — CI проходит
#   break-test      ошибка в правиле предметной области — падают тесты и мутации
#   break-migration миграция с ошибкой — падают «Миграции» и интеграционные тесты
#   add-secret      в код добавлен токен GitHub — его находит gitleaks
#   delete-test     удалён тест — падает make policy (меньше минимума тестов)
#   skip-test       тест помечен skip без обоснования — падает make policy
#   lower-threshold порог покрытия снижен до 50 % — падает make policy
#   disable-check   из pipeline убран этап мутационного тестирования — make policy
set -euo pipefail
cd "$(dirname "$0")/.."

SCENARIO="${1:-}"
BASE="${BASE:-main}"
[ -n "$SCENARIO" ] || { sed -n '2,22p' "$0"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "Есть незакоммиченные изменения" >&2; exit 1; }

git switch -q "$BASE"
git switch -q -c "demo/$SCENARIO"

case "$SCENARIO" in
    ok)
        echo "" >> docs/ci.md
        echo "<!-- демонстрация: корректное изменение $(date +%F) -->" >> docs/ci.md
        message="docs: демонстрация корректного изменения" ;;
    break-test)
        # остаток больше нельзя списать целиком: «>» заменено на «>=»
        sed -i 's/if requested > current:/if requested >= current:/' app/domain.py
        message="feat: (демо) ошибка в правиле списания" ;;
    break-migration)
        cat > migrations/versions/0005_demo_broken.py <<'PY'
"""Демонстрация: миграция с ошибкой (несуществующая таблица)."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE no_such_table ADD COLUMN broken integer")


def downgrade() -> None:
    op.execute("ALTER TABLE no_such_table DROP COLUMN broken")
PY
        message="feat: (демо) миграция с ошибкой" ;;
    add-secret)
        # токен собирается при запуске, чтобы в самом скрипте его не было
        token="ghp_$(head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 36)"
        printf '"""Демонстрация: секрет в коде."""\n\nGITHUB_TOKEN = "%s"\n' "$token" \
            > app/demo_settings.py
        message="feat: (демо) токен в коде" ;;
    delete-test)
        python3 - <<'PY'
import re, pathlib
p = pathlib.Path("tests/api/test_write_offs.py")
s = p.read_text(encoding="utf-8")
s = re.sub(r"\n\ndef test_[^\n]*\n(?:(?:    [^\n]*)?\n)*", "\n\n", s, count=1)
p.write_text(s, encoding="utf-8")
PY
        message="test: (демо) удалён «мешающий» тест" ;;
    skip-test)
        sed -i '0,/^def test_/s//@pytest.mark.skip(reason="мешает")\ndef test_/' tests/api/test_write_offs.py
        grep -q '^import pytest' tests/api/test_write_offs.py || sed -i '1a import pytest' tests/api/test_write_offs.py
        message="test: (демо) тест пропускается" ;;
    lower-threshold)
        sed -i 's/^fail_under = .*/fail_under = 50/' pyproject.toml
        message="chore: (демо) порог покрытия снижен" ;;
    disable-check)
        sed -i '/make mutation/d' .github/workflows/ci.yml
        message="ci: (демо) мутационное тестирование убрано из pipeline" ;;
    *)
        echo "Неизвестный сценарий: $SCENARIO" >&2
        git switch -q "$BASE"; git branch -q -D "demo/$SCENARIO"
        exit 1 ;;
esac

git add -A
git commit -q -m "$message"
git --no-pager show --stat --oneline HEAD
echo
echo "Ветка demo/$SCENARIO готова:"
echo "  git push -u origin demo/$SCENARIO"
echo "  gh pr create --base main --fill      # или merge request через сайт"
echo "После показа: git switch main && git branch -D demo/$SCENARIO"
echo "              git push origin --delete demo/$SCENARIO"
