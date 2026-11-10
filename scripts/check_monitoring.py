"""Проверка конфигурации наблюдаемости (ЛР8): make monitoring-lint.

promtool проверяет синтаксис Prometheus и выполняет unit-тесты правил. Этот
скрипт проверяет то, что синтаксис не ловит: правило с опечаткой в имени
метрики корректно, но никогда не сработает, а ссылка на несуществующий раздел
инструкции бесполезна в момент сбоя.

  - у каждого правила оповещения есть severity, summary, description и runbook;
  - раздел runbook существует в docs/runbook.md;
  - для каждого правила есть unit-тест, в котором оповещение СРАБАТЫВАЕТ;
  - метрики приложения (warehouse_*) в правилах и на панели действительно
    объявлены в app/metrics.py;
  - Prometheus собирает приложение, проверки доступности, хост и контейнеры;
  - на панели Grafana есть доступность, нагрузка, ошибки, время ответа,
    ресурсы и предметная метрика; все запросы — к источнику prometheus.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MONITORING = ROOT / "monitoring"
RULES_DIR = MONITORING / "prometheus" / "rules"
TESTS_DIR = MONITORING / "prometheus" / "tests"
PROMETHEUS = MONITORING / "prometheus" / "prometheus.yml"
DASHBOARDS = MONITORING / "grafana" / "dashboards"
RUNBOOK = ROOT / "docs" / "runbook.md"
APP_METRICS = ROOT / "app" / "metrics.py"

SEVERITIES = {"critical", "warning", "info"}
REQUIRED_ANNOTATIONS = ("summary", "description", "runbook")
REQUIRED_JOBS = {"warehouse-app", "blackbox-http", "node", "cadvisor"}
DATASOURCE_UID = "prometheus"
# что обязано быть на панели: раздел задания → метрика в запросах
DASHBOARD_REQUIRED = {
    "доступность": "probe_success",
    "нагрузка": "warehouse_http_requests_total",
    "ошибки": 'status=~"5..',
    "время ответа": "warehouse_http_request_duration_seconds_bucket",
    "ресурсы контейнеров": "container_memory_working_set_bytes",
    "ресурсы хоста": "node_filesystem_avail_bytes",
    "предметная метрика": "warehouse_materials_below_min",
}
APP_METRIC_RE = re.compile(r"\bwarehouse_[a-z_]+\b")
HISTOGRAM_SUFFIXES = ("_bucket", "_count", "_sum")


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def github_anchor(heading: str) -> str:
    """Якорь заголовка Markdown так, как его строит GitHub."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def runbook_anchors() -> set[str]:
    if not RUNBOOK.exists():
        return set()
    headings = re.findall(r"^#{1,6}\s+(.+?)\s*$", RUNBOOK.read_text(encoding="utf-8"), re.M)
    return {github_anchor(h) for h in headings}


def declared_app_metrics() -> set[str]:
    text = APP_METRICS.read_text(encoding="utf-8")
    names = set(re.findall(r'"(warehouse_[a-z_]+)"', text))
    # Counter экспортируется с суффиксом _total, Histogram — с _bucket/_count/_sum
    exported = set(names)
    for name in names:
        exported |= {name + suffix for suffix in HISTOGRAM_SUFFIXES}
        if not name.endswith("_total"):
            exported.add(name + "_total")
    return exported


def alert_rules() -> list[tuple[Path, dict]]:
    rules = []
    for path in sorted(RULES_DIR.glob("*.yml")):
        for group in load_yaml(path).get("groups", []):
            rules += [(path, rule) for rule in group.get("rules", []) if "alert" in rule]
    return rules


def firing_tests() -> set[str]:
    """Имена оповещений, для которых в тестах есть случай «срабатывает»."""
    fired: set[str] = set()
    for path in sorted(TESTS_DIR.glob("*.yml")):
        for test in load_yaml(path).get("tests", []):
            for case in test.get("alert_rule_test", []):
                if case.get("exp_alerts"):
                    fired.add(case["alertname"])
    return fired


def check_rules(app_metrics: set[str]) -> list[str]:
    problems: list[str] = []
    rules = alert_rules()
    if not rules:
        return [f"нет правил оповещений в {RULES_DIR.relative_to(ROOT)}"]
    anchors = runbook_anchors()
    if not anchors:
        problems.append(f"нет инструкции по диагностике {RUNBOOK.relative_to(ROOT)}")
    fired = firing_tests()
    for path, rule in rules:
        name = rule["alert"]
        where = f"{path.relative_to(ROOT)}: {name}"
        severity = (rule.get("labels") or {}).get("severity")
        if severity not in SEVERITIES:
            problems.append(f"{where}: severity {severity!r}, допустимо {sorted(SEVERITIES)}")
        annotations = rule.get("annotations") or {}
        missing = [key for key in REQUIRED_ANNOTATIONS if not annotations.get(key)]
        problems += [f"{where}: нет аннотации {key}" for key in missing]
        runbook = annotations.get("runbook", "")
        if runbook:
            file, _, anchor = runbook.partition("#")
            if file != "docs/runbook.md" or anchor not in anchors:
                problems.append(f"{where}: раздел инструкции {runbook} не найден в docs/runbook.md")
        if name not in fired:
            problems.append(f"{where}: нет unit-теста, в котором оповещение срабатывает")
        for metric in APP_METRIC_RE.findall(rule.get("expr", "")):
            if metric not in app_metrics:
                problems.append(f"{where}: метрики {metric} нет в app/metrics.py")
    return problems


def check_prometheus() -> list[str]:
    config = load_yaml(PROMETHEUS)
    jobs = {job.get("job_name") for job in config.get("scrape_configs", [])}
    missing = REQUIRED_JOBS - jobs
    return [f"prometheus.yml: нет сбора метрик {sorted(missing)}"] if missing else []


def _panels(panels: list[dict]) -> list[dict]:
    result = []
    for panel in panels:
        result.append(panel)
        result += _panels(panel.get("panels", []))
    return result


def check_dashboards(app_metrics: set[str]) -> list[str]:
    files = sorted(DASHBOARDS.glob("*.json"))
    if not files:
        return [f"нет панелей Grafana в {DASHBOARDS.relative_to(ROOT)}"]
    problems: list[str] = []
    expressions: list[str] = []
    uids: set[str] = set()
    for path in files:
        where = path.relative_to(ROOT)
        try:
            dashboard = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            problems.append(f"{where}: неверный JSON — {error}")
            continue
        uid = dashboard.get("uid")
        if not uid or uid in uids:
            problems.append(f"{where}: нет uid или uid повторяется")
        uids.add(uid)
        for panel in _panels(dashboard.get("panels", [])):
            if panel.get("type") == "row":
                continue
            title = panel.get("title", "?")
            if (panel.get("datasource") or {}).get("uid") != DATASOURCE_UID:
                problems.append(f"{where}: панель «{title}» — источник не {DATASOURCE_UID}")
            targets = [t.get("expr", "") for t in panel.get("targets", [])]
            if not any(targets):
                problems.append(f"{where}: панель «{title}» без запроса")
            expressions += targets
    text = "\n".join(expressions)
    for part, needle in DASHBOARD_REQUIRED.items():
        if needle not in text:
            problems.append(f"панели Grafana: нет раздела «{part}» ({needle})")
    for metric in sorted(set(APP_METRIC_RE.findall(text)) - app_metrics):
        problems.append(f"панели Grafana: метрики {metric} нет в app/metrics.py")
    return problems


def main() -> int:
    app_metrics = declared_app_metrics()
    problems = check_rules(app_metrics) + check_prometheus() + check_dashboards(app_metrics)
    if problems:
        print("Нарушения в конфигурации наблюдаемости (docs/observability.md):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        f"Наблюдаемость: {len(alert_rules())} правил оповещений с тестами и инструкцией, "
        f"панели и сбор метрик соответствуют требованиям."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
