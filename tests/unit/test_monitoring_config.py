"""Проверка конфигурации наблюдаемости (scripts/check_monitoring.py, ЛР8).

Ошибки, которые не ловит promtool: правило с опечаткой в имени метрики
синтаксически верно, но никогда не сработает; ссылка на несуществующий
раздел инструкции бесполезна в момент сбоя.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_monitoring", ROOT / "scripts" / "check_monitoring.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Проверка, направленная на копию конфигурации во временном каталоге."""
    module = load_checker()
    shutil.copytree(ROOT / "monitoring", tmp_path / "monitoring")
    (tmp_path / "docs").mkdir()
    shutil.copy(ROOT / "docs" / "runbook.md", tmp_path / "docs" / "runbook.md")
    monitoring = tmp_path / "monitoring"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "RULES_DIR", monitoring / "prometheus" / "rules")
    monkeypatch.setattr(module, "TESTS_DIR", monitoring / "prometheus" / "tests")
    monkeypatch.setattr(module, "PROMETHEUS", monitoring / "prometheus" / "prometheus.yml")
    monkeypatch.setattr(module, "DASHBOARDS", monitoring / "grafana" / "dashboards")
    monkeypatch.setattr(module, "RUNBOOK", tmp_path / "docs" / "runbook.md")
    return module


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_repository_monitoring_config_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert load_checker().main() == 0
    assert "правил оповещений" in capsys.readouterr().out


def test_runbook_anchor_matches_github() -> None:
    assert load_checker().github_anchor("1. Сервис недоступен") == "1-сервис-недоступен"


def test_misspelled_metric_in_rule_is_reported(checker: ModuleType) -> None:
    edit(
        checker.RULES_DIR / "warehouse.yml",
        "max(warehouse_database_up)",
        "max(warehouse_db_up)",
    )
    problems = checker.check_rules(checker.declared_app_metrics())
    assert any("warehouse_db_up нет в app/metrics.py" in p for p in problems)


def test_rule_without_firing_test_is_reported(checker: ModuleType) -> None:
    edit(
        checker.TESTS_DIR / "warehouse_test.yml",
        "alertname: DatabaseUnavailable",
        "alertname: SomethingElse",
    )
    problems = checker.check_rules(checker.declared_app_metrics())
    assert any("DatabaseUnavailable: нет unit-теста" in p for p in problems)


def test_missing_runbook_section_is_reported(checker: ModuleType) -> None:
    edit(checker.RUNBOOK, "## 9. Утечка секрета в журнал", "## 9. Секреты")
    problems = checker.check_rules(checker.declared_app_metrics())
    assert any("SecretRedactedInLogs: раздел инструкции" in p for p in problems)


def test_dashboard_without_domain_metric_is_reported(checker: ModuleType) -> None:
    path = checker.DASHBOARDS / "warehouse-overview.json"
    dashboard = json.loads(path.read_text(encoding="utf-8"))
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            target["expr"] = target["expr"].replace("warehouse_materials_below_min", "vector(0)")
    path.write_text(json.dumps(dashboard), encoding="utf-8")
    problems = checker.check_dashboards(checker.declared_app_metrics())
    assert any("предметная метрика" in p for p in problems)
