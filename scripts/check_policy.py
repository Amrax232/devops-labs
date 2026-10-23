"""Проверка политики качества (docs/quality-policy.md).

Запрещено без обоснования:
  - пропускать тесты (skip, skipif, xfail, importorskip);
  - отключать предупреждения анализаторов (# noqa, # nosec, # pragma: no cover,
    # pragma: no mutate);
  - снижать пороги покрытия и мутационного тестирования;
  - расширять списки исключений ruff и bandit;
  - убирать обязательные шаги из make verify;
  - убирать из шаблона merge request обязательные проверки (make verify,
    make container-check);
  - удалять тесты: число тестовых функций не ниже минимума из pyproject.toml;
  - убирать этапы из pipeline CI, разрешать им падать (continue-on-error,
    «|| true») и публиковать образ без успешных проверок;
  - оставлять критические файлы без владельцев в .github/CODEOWNERS;
  - принимать уязвимости зависимостей без обоснования и срока пересмотра.

Обоснование пишется в той же строке после « - » или « — », не короче 10 символов:
    import x  # noqa: F401 - модуль регистрирует модели при импорте

Запуск: make policy (входит в make verify).
"""

from __future__ import annotations

import ast
import datetime as dt
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Нижние границы порогов. Изменить их можно только изменением этого файла —
# он относится к критическим и проверяется всей командой в merge request.
COVERAGE_FLOOR = 80
MUTATION_FLOOR = 80
TESTS_FLOOR = 106  # тестовых функций на момент ЛР5; уменьшить — только изменением этого файла

ALLOWED_RUFF_IGNORES = {"B008"}  # Depends() в аргументах — стандартный приём FastAPI
ALLOWED_PER_FILE_IGNORES = {
    "tests/*": {"E501"},  # длинные строки с тестовыми данными в parametrize
}
REQUIRED_VERIFY_STEPS = [
    "policy",
    "secrets",
    "secrets-scan",
    "lint",
    "sast",
    "deps-audit",
    "container-lint",
    "test-db",
    "coverage",
    "mutation",
]
# Изменения контейнерной среды принимаются только после make container-check:
# пункт об этом обязан быть в шаблоне merge request.
PR_TEMPLATE = ".github/pull_request_template.md"
PR_REQUIRED_CHECKS = ["make verify", "make container-check"]

# Pipeline CI: какие make-цели обязаны выполняться и на каком этапе
CI_WORKFLOW = ".github/workflows/ci.yml"
CI_REQUIRED_TARGETS = {
    "lint": ["policy", "lint", "container-lint"],
    "test": ["test-db", "coverage", "mutation"],
    "migrations": ["migrations-check"],
    "backup": ["backup-check"],
    "security": ["secrets", "secrets-scan", "sast", "deps-audit"],
    "container": ["container-check", "image-scan"],
}
CI_PUBLISH_JOB = "publish"
CI_GATE_JOB = "gate"

# Критические файлы приёмки: у каждого должен быть владелец в CODEOWNERS
CODEOWNERS_FILE = ".github/CODEOWNERS"
CRITICAL_FILES = [
    "Makefile",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements.lock",
    ".gitleaks.toml",
    "security/vulnerability-exceptions.toml",
    "scripts/check_policy.py",
    "scripts/check_containers.py",
    "tests/conftest.py",
    "tests/unit/test_domain.py",
    ".github/workflows/ci.yml",
    ".github/CODEOWNERS",
    "Dockerfile",
    "docker-compose.yml",
    "migrations/env.py",
]

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


def check_pr_template() -> list[str]:
    path = ROOT / PR_TEMPLATE
    if not path.exists():
        return [f"нет шаблона merge request {PR_TEMPLATE}"]
    text = path.read_text(encoding="utf-8")
    return [
        f"в шаблоне merge request нет обязательной проверки «{check}»"
        for check in PR_REQUIRED_CHECKS
        if f"`{check}`" not in text
    ]


def count_test_functions() -> int:
    total = 0
    for path in (ROOT / "tests").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        total += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        )
    return total


def check_tests_count() -> list[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    minimum = config.get("tool", {}).get("warehouse", {}).get("quality", {})
    minimum = minimum.get("min_test_functions", 0)
    problems = []
    if minimum < TESTS_FLOOR:
        problems.append(f"минимум тестов {minimum} ниже допустимого {TESTS_FLOOR}")
    actual = count_test_functions()
    if actual < max(minimum, TESTS_FLOOR):
        problems.append(
            f"тестовых функций {actual}, а должно быть не меньше {max(minimum, TESTS_FLOOR)}"
            " — тесты удалены"
        )
    return problems


def _make_targets(job: dict) -> list[str]:
    targets = []
    for step in job.get("steps", []):
        for line in str(step.get("run", "")).splitlines():
            match = re.match(r"\s*make\s+([\w-]+)", line)
            if match:
                targets.append(match.group(1))
    return targets


def check_ci() -> list[str]:
    path = ROOT / CI_WORKFLOW
    if not path.exists():
        return [f"нет pipeline {CI_WORKFLOW}"]
    import yaml  # PyYAML ставится вместе с uvicorn[standard]

    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = workflow.get(True) or workflow.get("on") or {}  # YAML 1.1: «on» → True
    problems = [
        f"pipeline не запускается по событию {event}"
        for event in ("push", "pull_request")
        if event not in triggers
    ]
    jobs = workflow.get("jobs", {})
    for name, targets in CI_REQUIRED_TARGETS.items():
        if name not in jobs:
            problems.append(f"в pipeline нет этапа {name}")
            continue
        present = _make_targets(jobs[name])
        problems += [
            f"этап {name} не выполняет make {target}" for target in targets if target not in present
        ]
    text = path.read_text(encoding="utf-8")
    if re.search(r"continue-on-error:\s*(true|\$\{\{)", text):
        problems.append("в pipeline этапу разрешено падать (continue-on-error)")
    if re.search(r"make\s+[\w-][^\n#]*\|\|\s*(true|exit 0|:)", text):
        problems.append("в pipeline ошибка make подавлена («|| true»)")

    checks = set(CI_REQUIRED_TARGETS)
    publish = jobs.get(CI_PUBLISH_JOB, {})
    needs = set(publish.get("needs", []))
    if not publish:
        problems.append("в pipeline нет этапа публикации образа")
    elif not checks <= needs:
        problems.append(f"публикация не ждёт этапов: {sorted(checks - needs)}")
    elif "refs/heads/main" not in str(publish.get("if", "")):
        problems.append("образ публикуется не только из main")
    gate = jobs.get(CI_GATE_JOB, {})
    if not checks <= set(gate.get("needs", [])) or "always()" not in str(gate.get("if", "")):
        problems.append("итоговая проверка ci-gate должна зависеть от всех этапов (if: always())")
    return problems


def check_codeowners() -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from critical_changes import load_codeowners, owners_of

    path = ROOT / CODEOWNERS_FILE
    if not path.exists():
        return [f"нет {CODEOWNERS_FILE}: критические файлы не защищены"]
    if "@CHANGE_ME" in path.read_text(encoding="utf-8"):
        return [f"в {CODEOWNERS_FILE} заглушки CHANGE_ME: выполните scripts/setup_github.sh"]
    rules = load_codeowners(path)
    return [
        f"критический файл {name} без владельца в {CODEOWNERS_FILE}"
        for name in CRITICAL_FILES
        if not owners_of(name, rules)
    ]


def check_vulnerability_exceptions() -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from deps_audit import load_exceptions

    return load_exceptions(dt.date.today())[1]


def main() -> int:
    problems = (
        check_sources()
        + check_config()
        + check_makefile()
        + check_pr_template()
        + check_tests_count()
        + check_ci()
        + check_codeowners()
        + check_vulnerability_exceptions()
    )
    if problems:
        print("Нарушения политики качества (docs/quality-policy.md):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Политика качества соблюдена.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
