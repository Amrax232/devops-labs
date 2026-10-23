"""Проверка зависимостей на известные уязвимости: make deps-audit.

Проверяются ровно те версии, что зафиксированы в requirements.lock (их же ставит
make setup и Dockerfile), по базе уязвимостей PyPI/OSV с помощью pip-audit.
Найдена уязвимость — проверка падает. Исключение возможно только через
security/vulnerability-exceptions.toml: с обоснованием и сроком пересмотра.

    python scripts/deps_audit.py                     # проверка, отчёт reports/pip-audit.json
    python scripts/deps_audit.py --trivyignore FILE  # исключения для trivy (make image-scan)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess  # nosec B404 - запускается только pip-audit с фиксированными аргументами
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock"
EXCEPTIONS = ROOT / "security" / "vulnerability-exceptions.toml"
REPORT = ROOT / "reports" / "pip-audit.json"
MAX_DAYS = 180
MIN_REASON = 30


def load_exceptions(today: dt.date | None = None) -> tuple[list[dict], list[str]]:
    """Исключения и список нарушений правил их оформления."""
    today = today or dt.date.today()
    if not EXCEPTIONS.exists():
        return [], []
    data = tomllib.loads(EXCEPTIONS.read_text(encoding="utf-8"))
    entries = data.get("exception", [])
    problems: list[str] = []
    for number, entry in enumerate(entries, 1):
        where = f"{EXCEPTIONS.relative_to(ROOT)}: исключение №{number}"
        ids = entry.get("ids") or []
        if not ids or not all(isinstance(item, str) and item for item in ids):
            problems.append(f"{where}: нет идентификаторов уязвимости (ids)")
        if not entry.get("package"):
            problems.append(f"{where}: не указан пакет (package)")
        if len(str(entry.get("reason", "")).strip()) < MIN_REASON:
            problems.append(f"{where}: обоснование короче {MIN_REASON} символов")
        expires = entry.get("expires")
        if not isinstance(expires, dt.date):
            problems.append(f"{where}: нет срока пересмотра (expires = ГГГГ-ММ-ДД)")
        elif expires < today:
            problems.append(f"{where}: срок пересмотра {expires} истёк — обновите пакет")
        elif expires > today + dt.timedelta(days=MAX_DAYS):
            problems.append(f"{where}: срок пересмотра дальше {MAX_DAYS} дней")
    return entries, problems


def write_trivyignore(path: Path, entries: list[dict]) -> None:
    lines = ["# Создан scripts/deps_audit.py из security/vulnerability-exceptions.toml"]
    for entry in entries:
        lines.append(f"# {entry['package']}: {' '.join(str(entry['reason']).split())[:120]}")
        lines += [f"{vuln_id} exp:{entry['expires']}" for vuln_id in entry["ids"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit(entries: list[dict]) -> int:
    if not LOCK.exists():
        print("Нет requirements.lock: выполните make lock и закоммитьте файл", file=sys.stderr)
        return 1
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip_audit",
        "--requirement",
        str(LOCK),
        "--no-deps",
        "--disable-pip",
        "--progress-spinner",
        "off",
        "--format",
        "json",
        "--output",
        str(REPORT),
    ]
    for entry in entries:
        for vuln_id in entry["ids"]:
            command += ["--ignore-vuln", vuln_id]
    result = subprocess.run(command, cwd=ROOT, check=False)  # nosec B603 - без оболочки
    if not REPORT.exists():
        print("pip-audit не сформировал отчёт", file=sys.stderr)
        return result.returncode or 1

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    dependencies = report.get("dependencies", [])
    found = [(dep, vuln) for dep in dependencies for vuln in dep.get("vulns", [])]
    print(f"Проверено пакетов: {len(dependencies)} (requirements.lock)")
    for entry in entries:
        print(f"  принятое исключение: {entry['package']} {', '.join(entry['ids'])}")
    if found:
        print(f"Найдено уязвимостей: {len(found)}")
        for dep, vuln in found:
            fix = ", ".join(vuln.get("fix_versions") or []) or "исправления нет"
            aliases = ", ".join(vuln.get("aliases") or [])
            name = f"{dep['name']} {dep['version']}"
            print(f"  - {name}: {vuln['id']} ({aliases}); исправлено: {fix}")
        print("Обновите пакет или оформите исключение в security/vulnerability-exceptions.toml")
        return 1
    if result.returncode != 0:
        return result.returncode
    print("Известных уязвимостей в зависимостях нет.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trivyignore", type=Path, help="записать исключения для trivy")
    args = parser.parse_args(argv)

    entries, problems = load_exceptions()
    if problems:
        print("Исключения оформлены неверно:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    if args.trivyignore:
        write_trivyignore(args.trivyignore, entries)
        print(f"Исключения для trivy: {args.trivyignore} ({len(entries)})")
        return 0
    return audit(entries)


if __name__ == "__main__":
    sys.exit(main())
