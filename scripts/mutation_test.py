"""Мутационное тестирование правил предметной области.

Идея: в код намеренно вносится маленькая ошибка («мутант») — например, `<`
заменяется на `<=`, условие проверки удаляется, `+` становится `-`. Затем
запускаются тесты. Если тесты упали — мутант «убит», то есть тесты заметили
ошибку. Если прошли — мутант «выжил»: в тестах есть дыра. Доля убитых мутантов
показывает, насколько тесты на самом деле проверяют логику, а не просто
выполняют строки кода (это и отличает мутационное тестирование от покрытия).

Запуск:  make mutation
         python scripts/mutation_test.py --target app/domain.py --tests tests/unit

Скрипт не меняет файлы проекта: каждый мутант проверяется во временной копии.
Строку можно исключить комментарием «# pragma: no mutate - <обоснование>»;
обоснование обязательно (проверяется scripts/check_policy.py).
"""

from __future__ import annotations

import argparse
import ast
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRAGMA = "pragma: no mutate"

COMPARE_SWAPS: dict[type, list[type]] = {
    ast.Lt: [ast.LtE, ast.Gt],
    ast.LtE: [ast.Lt, ast.Gt],
    ast.Gt: [ast.GtE, ast.Lt],
    ast.GtE: [ast.Gt, ast.Lt],
    ast.Eq: [ast.NotEq],
    ast.NotEq: [ast.Eq],
    ast.Is: [ast.IsNot],
    ast.IsNot: [ast.Is],
    ast.In: [ast.NotIn],
    ast.NotIn: [ast.In],
}
BINOP_SWAPS: dict[type, list[type]] = {
    ast.Add: [ast.Sub],
    ast.Sub: [ast.Add],
    ast.Mult: [ast.Div],
    ast.Div: [ast.Mult],
}
SYMBOLS = {
    ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==",
    ast.NotEq: "!=", ast.Is: "is", ast.IsNot: "is not", ast.In: "in",
    ast.NotIn: "not in", ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.And: "and", ast.Or: "or",
}  # fmt: skip


@dataclass
class Mutation:
    line: int
    description: str
    apply: Callable[[], None]


# ------------------------------------------------------------------ поиск мутантов
def _walk(node: ast.AST, parent=None, field=None, index=None) -> Iterator[tuple]:
    """Обход дерева в фиксированном порядке вместе с местом узла в родителе."""
    yield node, parent, field, index
    for name, value in ast.iter_fields(node):
        if isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, ast.AST):
                    yield from _walk(item, node, name, i)
        elif isinstance(value, ast.AST):
            yield from _walk(value, node, name, None)


def _replace(parent: ast.AST, field: str, index: int | None, new: ast.AST) -> None:
    if index is None:
        setattr(parent, field, new)
    else:
        getattr(parent, field)[index] = new


def _is_docstring(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def find_mutations(tree: ast.AST, skip_lines: set[int]) -> list[Mutation]:
    """Все точки мутации. Порядок детерминирован, поэтому мутант №k всегда один и тот же."""
    found: list[Mutation] = []

    for node, parent, field, index in _walk(tree):
        line = getattr(node, "lineno", 0)
        if line in skip_lines:
            continue

        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                for new in COMPARE_SWAPS.get(type(op), []):
                    found.append(Mutation(
                        line, f"{SYMBOLS[type(op)]} → {SYMBOLS[new]}",
                        lambda n=node, i=i, new=new: n.ops.__setitem__(i, new()),
                    ))  # fmt: skip

        elif isinstance(node, ast.BinOp | ast.AugAssign):
            for new in BINOP_SWAPS.get(type(node.op), []):
                found.append(Mutation(
                    line, f"{SYMBOLS[type(node.op)]} → {SYMBOLS[new]}",
                    lambda n=node, new=new: setattr(n, "op", new()),
                ))  # fmt: skip

        elif isinstance(node, ast.BoolOp):
            new = ast.Or if isinstance(node.op, ast.And) else ast.And
            found.append(Mutation(
                line, f"{SYMBOLS[type(node.op)]} → {SYMBOLS[new]}",
                lambda n=node, new=new: setattr(n, "op", new()),
            ))  # fmt: skip

        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            found.append(Mutation(
                line, "убрано «not»",
                lambda n=node, p=parent, f=field, i=index: _replace(p, f, i, n.operand),
            ))  # fmt: skip

        elif isinstance(node, ast.Constant) and type(node.value) in (bool, int, float):
            if isinstance(node.value, bool):
                new_value: object = not node.value
            else:
                new_value = node.value + 1
            found.append(Mutation(
                line, f"{node.value!r} → {new_value!r}",
                lambda n=node, v=new_value: setattr(n, "value", v),
            ))  # fmt: skip

        elif isinstance(node, ast.Raise):
            found.append(Mutation(
                line, "убрано исключение (raise → pass)",
                lambda p=parent, f=field, i=index, n=node: _replace(p, f, i, _pass_like(n)),
            ))  # fmt: skip

        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if not _is_docstring(node):
                found.append(Mutation(
                    line, "удалён вызов (проверка не выполняется)",
                    lambda p=parent, f=field, i=index, n=node: _replace(p, f, i, _pass_like(n)),
                ))  # fmt: skip

        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                found.append(Mutation(
                    line, "return <значение> → return None",
                    lambda n=node: setattr(n, "value", ast.Constant(value=None)),
                ))  # fmt: skip

    return found


def _pass_like(node: ast.AST) -> ast.Pass:
    return ast.copy_location(ast.Pass(), node)


def build_mutant(source: str, number: int, skip_lines: set[int]) -> tuple[str, Mutation]:
    tree = ast.parse(source)
    mutation = find_mutations(tree, skip_lines)[number]
    mutation.apply()
    ast.fix_missing_locations(tree)
    return ast.unparse(tree), mutation


def pragma_lines(source: str) -> set[int]:
    return {n for n, text in enumerate(source.splitlines(), start=1) if PRAGMA in text}


# --------------------------------------------------------------------- прогон тестов
def prepare_workspace(tests_dir: Path) -> Path:
    """Временная копия кода и тестов: файлы проекта никогда не изменяются."""
    work = Path(tempfile.mkdtemp(prefix="mutation-"))
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "app", work / "app", ignore=ignore)
    (work / "tests").mkdir()
    for name in ("__init__.py", "conftest.py"):
        if (ROOT / "tests" / name).exists():
            shutil.copy2(ROOT / "tests" / name, work / "tests" / name)
    rel = tests_dir.resolve().relative_to(ROOT)
    shutil.copytree(ROOT / rel, work / rel, ignore=ignore)
    if (ROOT / "pyproject.toml").exists():
        shutil.copy2(ROOT / "pyproject.toml", work / "pyproject.toml")
    return work


def run_tests(command: list[str], work: Path, timeout: float) -> tuple[str, float]:
    env = dict(os.environ)
    # байт-код не кешируется: иначе Python может выполнить старую версию мутанта
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(work), env.get("PYTHONPATH")]))
    started = time.monotonic()
    try:
        result = subprocess.run(  # nosec B603 - команда задаётся разработчиком, не пользователем
            command, cwd=work, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return "timeout", time.monotonic() - started
    status = "passed" if result.returncode == 0 else "failed"
    return status, time.monotonic() - started


# --------------------------------------------------------------------------- отчёт
def default_min_score() -> float:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return float(config["tool"]["warehouse"]["quality"]["mutation_min_score"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", default="app/domain.py", help="модуль для мутаций")
    parser.add_argument("--tests", default="tests/unit", help="каталог тестов")
    parser.add_argument("--min-score", type=float, default=None, help="порог, %%")
    parser.add_argument("--runner", default=None, help="команда запуска тестов")
    parser.add_argument("--report", default="reports/mutation.txt")
    parser.add_argument("--list", action="store_true", help="только показать мутантов")
    args = parser.parse_args()

    target = (ROOT / args.target).resolve()
    tests_dir = ROOT / args.tests
    min_score = args.min_score if args.min_score is not None else default_min_score()
    source = target.read_text(encoding="utf-8")
    skip = pragma_lines(source)
    lines = source.splitlines()
    total = len(find_mutations(ast.parse(source), skip))

    if args.list:
        for number, mutation in enumerate(find_mutations(ast.parse(source), skip), start=1):
            print(f"{number:3}  строка {mutation.line:4}  {mutation.description}")
        print(f"всего мутантов: {total}")
        return 0

    command = (
        shlex.split(args.runner)
        if args.runner
        else [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", args.tests]
    )
    work = prepare_workspace(tests_dir)
    mutant_path = work / target.relative_to(ROOT)
    try:
        print(f"Цель: {args.target}, тесты: {args.tests}, мутантов: {total}")
        status, baseline = run_tests(command, work, timeout=600)
        if status != "passed":
            print("Тесты падают на исходном коде — сначала почините их.", file=sys.stderr)
            return 2
        timeout = max(10.0, baseline * 5)

        killed, survived = 0, []
        for number in range(total):
            mutant_source, mutation = build_mutant(source, number, skip)
            mutant_path.write_text(mutant_source, encoding="utf-8")
            status, _ = run_tests(command, work, timeout)
            if status == "passed":
                survived.append(mutation)
                mark = "ВЫЖИЛ"
            else:
                killed += 1
                mark = "убит" if status == "failed" else "убит (таймаут)"
            print(f"  [{number + 1:3}/{total}] строка {mutation.line:4}  "
                  f"{mutation.description:42} {mark}")  # fmt: skip
        mutant_path.write_text(source, encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    score = 100.0 if total == 0 else killed * 100.0 / total
    report = [
        f"Мутационное тестирование: {args.target}",
        f"Тесты: {args.tests}",
        f"Мутантов: {total}, убито: {killed}, выжило: {len(survived)}",
        f"Оценка: {score:.1f}% (порог {min_score:.0f}%)",
        "",
    ]
    if survived:
        report.append("Выжившие мутанты — изменения, которые тесты НЕ заметили:")
        for mutation in survived:
            code = lines[mutation.line - 1].strip() if mutation.line else ""
            report.append(f"  строка {mutation.line}: {mutation.description}")
            report.append(f"      {code}")
    text = "\n".join(report)
    print("\n" + text)

    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text + "\n", encoding="utf-8")

    if score < min_score:
        print(f"\nОценка {score:.1f}% ниже порога {min_score:.0f}%.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
