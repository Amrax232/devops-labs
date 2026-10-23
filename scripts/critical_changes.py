"""Отчёт об изменении критических файлов приёмки: make critical-changes [BASE=origin/main].

Критические файлы — те, что перечислены в .github/CODEOWNERS: тесты, Makefile,
настройки анализаторов, pipeline, Dockerfile, миграции. Их изменение требует
одобрения владельца (защита ветки main), а этот отчёт делает изменение заметным:

  - список изменённых критических файлов;
  - сколько тестовых функций было и стало (удаление теста видно сразу);
  - в GitHub Actions (--github) — предупреждения в merge request и сводка
    в Summary запуска.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess  # nosec B404 - вызывается только git с фиксированными аргументами
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"


# --------------------------------------------------------------- CODEOWNERS
def pattern_regex(pattern: str) -> re.Pattern[str]:
    """Шаблон CODEOWNERS (синтаксис .gitignore) → регулярное выражение для пути."""
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    directory = pattern.endswith("/")
    body = pattern.strip("/")
    regex, i = "", 0
    while i < len(body):
        if body.startswith("**/", i):
            regex, i = regex + "(?:.*/)?", i + 3
        elif body.startswith("**", i):
            regex, i = regex + ".*", i + 2
        elif body[i] == "*":
            regex, i = regex + "[^/]*", i + 1
        elif body[i] == "?":
            regex, i = regex + "[^/]", i + 1
        else:
            regex, i = regex + re.escape(body[i]), i + 1
    prefix = "^" if anchored else "^(?:.*/)?"
    suffix = "/.*$" if directory else "(?:/.*)?$"
    return re.compile(prefix + regex + suffix)


def load_codeowners(path: Path = CODEOWNERS) -> list[tuple[str, re.Pattern[str], list[str]]]:
    rules = []
    if not path.exists():
        return rules
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        rules.append((pattern, pattern_regex(pattern), owners))
    return rules


def owners_of(path: str, rules: list[tuple[str, re.Pattern[str], list[str]]]) -> list[str]:
    """Владельцы файла: как в GitHub, побеждает последнее подходящее правило."""
    owners: list[str] = []
    for _, regex, rule_owners in rules:
        if regex.match(path):
            owners = rule_owners
    return owners


# --------------------------------------------------------------------- git
def git(*args: str) -> str:
    result = subprocess.run(  # nosec B603 B607 - git из PATH, аргументы фиксированы
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def count_tests(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    )


def tests_at(ref: str | None) -> int:
    """Число тестовых функций в tests/ на коммите ref (None — рабочая копия)."""
    if ref is None:
        return sum(count_tests(p.read_text(encoding="utf-8")) for p in ROOT.glob("tests/**/*.py"))
    files = git("ls-tree", "-r", "--name-only", ref, "--", "tests").split()
    return sum(count_tests(git("show", f"{ref}:{name}")) for name in files if name.endswith(".py"))


# ------------------------------------------------------------------ отчёт
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", nargs="?", default="origin/main", help="с чем сравнивать")
    parser.add_argument("--github", action="store_true", help="аннотации и Summary GitHub")
    args = parser.parse_args(argv)

    rules = load_codeowners()
    base = git("merge-base", args.base, "HEAD").strip()
    changes = [
        line.split("\t")
        for line in git("diff", "--name-status", "--no-renames", f"{base}...HEAD").splitlines()
        if line
    ]
    critical = [(status, path, owners_of(path, rules)) for status, path in changes]
    critical = [item for item in critical if item[2]]
    before, after = tests_at(base), tests_at("HEAD")

    status_names = {"A": "добавлен", "M": "изменён", "D": "УДАЛЁН"}
    lines = [
        "## Критические файлы приёмки",
        "",
        f"Сравнение с `{args.base}`: изменено файлов — {len(changes)}, "
        f"из них критических — {len(critical)}.",
        "",
        f"Тестовых функций: было {before}, стало {after}"
        + (f" — **удалено {before - after}**" if after < before else "")
        + ".",
        "",
    ]
    if critical:
        lines += ["| Файл | Изменение | Владельцы (обязательное одобрение) |", "|---|---|---|"]
        lines += [
            f"| `{path}` | {status_names.get(status[0], status)} | {' '.join(owners)} |"
            for status, path, owners in critical
        ]
    else:
        lines.append("Критические файлы не изменялись.")
    report = "\n".join(lines)
    print(report)

    if args.github:
        for status, path, owners in critical:
            level = "error" if status.startswith("D") and path.startswith("tests/") else "warning"
            print(
                f"::{level} file={path}::Критический файл {status_names.get(status[0], status)}"
                f" — нужно одобрение {' '.join(owners)}"
            )
        if after < before:
            print(f"::error::Удалено тестовых функций: {before - after} (было {before})")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
