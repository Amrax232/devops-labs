"""Проверка политики качества (docs/quality-policy.md).

Запрещено без обоснования:
  - пропускать тесты (skip, skipif, xfail, importorskip);
  - отключать предупреждения анализаторов (# noqa, # nosec, # pragma: no cover,
    # pragma: no mutate);
  - снижать пороги покрытия и мутационного тестирования;
  - расширять списки исключений ruff и bandit;
  - убирать обязательные шаги из make verify.

Обоснование пишется в той же строке после « - » или « — », не короче 10 символов:
    import x  # noqa: F401 - модуль регистрирует модели при импорте

Запуск: make policy (входит в make verify).
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Нижние границы порогов. Изменить их можно только изменением этого файла —
# он относится к критическим и проверяется всей командой в merge request.
COVERAGE_FLOOR = 80
MUTATION_FLOOR = 80

ALLOWED_RUFF_IGNORES = {"B008"}  # Depends() в аргументах — стандартный приём FastAPI
ALLOWED_PER_FILE_IGNORES = {
    "tests/*": {"E501"},  # длинные строки с тестовыми данными в parametrize
}
REQUIRED_VERIFY_STEPS = ["policy", "secrets", "lint", "sast", "test-db", "coverage", "mutation"]

SCANNED_DIRS = ["app", "scripts", "tests", "migrations"]
MIN_REASON = 10

SKIP_RE = re.compile(
    r"pytest\.mark\.(skip|skipif|xfail)\b|pytest\.(skip|xfail|importorskip)\(|unittest\.skip"
)
SUPPRESS_RE = re.compile(r"#\s*(noqa|nosec|pragma:\s*no\s+cover|pragma:\s*no\s+mutate)\b(.*)$")
NOQA_CODES_RE = re.compile(r"^:\s*[A-Z]+\d+(\s*,\s*[A-Z]+\d+)*")
NOSEC_CODES_RE = re.compile(r"^\s*B\d+(\s*,\s*B\d+)*")
REASON_RE = re.compile(r"\s[-—]\s*(.+)$")


def _reason_ok(tail: str) -> bool:
    match = REASON_RE.search(tail)
    return bool(match) and len(match.group(1).strip()) >= MIN_REASON


def check_sources() -> list[str]:
    problems: list[str] = []
    for directory in SCANNED_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            rel = path.relative_to(ROOT)
            if rel.as_posix() == "scripts/check_policy.py":
                continue  # файл описывает запрещённые конструкции и сам их не использует
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                where = f"{rel}:{number}"
                if rel.parts[0] == "tests" and SKIP_RE.search(line):
                    if not ("# policy" in line and _reason_ok(line.split("# policy", 1)[1])):
                        problems.append(f"{where}: пропуск теста без обоснования")
                match = SUPPRESS_RE.search(line)
                if not match:
                    continue
                kind, tail = match.group(1), match.group(2)
                if kind == "noqa" and not NOQA_CODES_RE.match(tail):
                    problems.append(f"{where}: # noqa без кода правила — подавляет всё подряд")
                elif kind == "nosec" and not NOSEC_CODES_RE.match(tail):
                    problems.append(f"{where}: # nosec без кода проверки bandit")
                elif not _reason_ok(tail):
                    problems.append(f"{where}: # {kind} без обоснования (« - причина»)")
    return problems


def check_config() -> list[str]:
    problems: list[str] = []
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tool = config.get("tool", {})

    coverage = tool.get("coverage", {}).get("report", {}).get("fail_under", 0)
    if coverage < COVERAGE_FLOOR:
        problems.append(f"порог покрытия {coverage}% ниже допустимого {COVERAGE_FLOOR}%")

    mutation = tool.get("warehouse", {}).get("quality", {}).get("mutation_min_score", 0)
    if mutation < MUTATION_FLOOR:
        problems.append(f"порог мутационного тестирования {mutation}% ниже {MUTATION_FLOOR}%")

    lint = tool.get("ruff", {}).get("lint", {})
    extra = set(lint.get("ignore", [])) - ALLOWED_RUFF_IGNORES
    if extra:
        problems.append(f"новые глобальные исключения ruff: {sorted(extra)}")
    for pattern, codes in lint.get("per-file-ignores", {}).items():
        extra = set(codes) - ALLOWED_PER_FILE_IGNORES.get(pattern, set())
        if extra:
            problems.append(f"новые исключения ruff для {pattern}: {sorted(extra)}")

    skips = tool.get("bandit", {}).get("skips", [])
    if skips:
        problems.append(f"bandit пропускает проверки: {skips}")

    addopts = tool.get("pytest", {}).get("ini_options", {}).get("addopts", "")
    for forbidden in ("--deselect", " -k ", "--ignore", "-p no:"):
        if forbidden.strip() in addopts.split() or forbidden in f" {addopts} ":
            problems.append(f"в настройках pytest запрещённый параметр «{forbidden.strip()}»")
    if "--strict-markers" not in addopts:
        problems.append("pytest должен запускаться с --strict-markers")
    return problems


def check_makefile() -> list[str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^verify:.*?(?=^\S)", text + "\nEND", re.S | re.M)
    if not match:
        return ["в Makefile нет цели verify"]
    block = match.group(0)
    # шаг считается выполняемым, только если он вызывается командой $(MAKE) <шаг>;
    # упоминание в echo или в комментарии не засчитывается
    return [
        f"make verify не запускает обязательный шаг «{step}»"
        for step in REQUIRED_VERIFY_STEPS
        if not re.search(rf"^\t@?\$\(MAKE\)[^\n#]*\s{re.escape(step)}\s*$", block, re.M)
    ]


def main() -> int:
    problems = check_sources() + check_config() + check_makefile()
    if problems:
        print("Нарушения политики качества (docs/quality-policy.md):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Политика качества соблюдена.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
