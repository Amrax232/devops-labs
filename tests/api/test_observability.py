"""Метрики Prometheus, идентификатор запроса и журнал запросов (ЛР8)."""

import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.logging_setup import JsonFormatter


def _metric(client: TestClient, name: str, **labels: str) -> float:
    """Значение ряда метрики из /metrics (0, если ряда ещё нет)."""
    text = client.get("/metrics").text
    for line in text.splitlines():
        if not line.startswith(name + ("{" if labels else " ")):
            continue
        if all(f'{key}="{value}"' in line for key, value in labels.items()):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def test_metrics_endpoint_is_open_and_in_prometheus_format(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    for name in (
        "warehouse_http_requests_total",
        "warehouse_http_request_duration_seconds_bucket",
        "warehouse_app_info",
        "warehouse_database_up",
        "warehouse_materials_below_min",
        "warehouse_stock_operations_total",
    ):
        assert name in response.text


def test_requests_counted_by_route_template(client: TestClient, material_id: int) -> None:
    labels = {"method": "GET", "endpoint": "/api/v1/materials/{material_id}", "status": "200"}
    before = _metric(client, "warehouse_http_requests_total", **labels)
    client.get(f"/api/v1/materials/{material_id}")
    assert _metric(client, "warehouse_http_requests_total", **labels) == before + 1


def test_errors_counted_with_status(anonymous_client: TestClient) -> None:
    labels = {"method": "POST", "endpoint": "/api/v1/units", "status": "401"}
    before = _metric(anonymous_client, "warehouse_http_requests_total", **labels)
    failures = _metric(anonymous_client, "warehouse_auth_failures_total")
    anonymous_client.post("/api/v1/units", json={"code": "kg", "name": "Килограмм"})
    assert _metric(anonymous_client, "warehouse_http_requests_total", **labels) == before + 1
    assert _metric(anonymous_client, "warehouse_auth_failures_total") == failures + 1


def test_domain_metrics(client: TestClient, material_id: int) -> None:
    """Материал с минимумом 50 и нулевым остатком — ниже минимального остатка."""
    assert _metric(client, "warehouse_database_up") == 1
    assert _metric(client, "warehouse_materials_total") == 1
    assert _metric(client, "warehouse_materials_below_min") == 1


def test_stock_operations_counted(client: TestClient, stocked_material_id: int) -> None:
    before = _metric(client, "warehouse_stock_operations_total", operation="write_off")
    response = client.post(
        f"/api/v1/materials/{stocked_material_id}/write-offs",
        json={"quantity": "1", "reason": "Брак"},
    )
    assert response.status_code == 201
    assert _metric(client, "warehouse_stock_operations_total", operation="write_off") == before + 1


def test_request_id_generated_and_propagated(client: TestClient) -> None:
    generated = client.get("/healthz").headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert (
        client.get("/healthz", headers={"X-Request-ID": "nginx-req-7"}).headers["X-Request-ID"]
        == "nginx-req-7"
    )
    # чужие символы не попадают в журнал как есть — создаётся новый идентификатор
    assert (
        client.get("/healthz", headers={"X-Request-ID": "bad id"}).headers["X-Request-ID"]
        != "bad id"
    )


def test_request_is_logged_with_endpoint_status_and_result(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.access"):
        response = client.get("/api/v1/materials/999999")
    record = next(r for r in caplog.records if getattr(r, "event", "") == "http_request")
    assert record.endpoint == "/api/v1/materials/{material_id}"
    assert record.status == 404 and record.result == "client_error"
    assert record.duration_ms >= 0
    assert response.headers["X-Request-ID"]


def test_password_never_reaches_log_output(client: TestClient) -> None:
    """Даже если код запишет пароль в журнал, в вывод он попадёт замаскированным,
    а метрика warehouse_log_secrets_redacted_total покажет, что это случилось."""
    handler = next(
        h for h in logging.getLogger().handlers if isinstance(h.formatter, JsonFormatter)
    )
    before = _metric(client, "warehouse_log_secrets_redacted_total")
    record = logging.makeLogRecord(
        {
            "name": "app.test",
            "levelname": "WARNING",
            "levelno": logging.WARNING,
            "msg": "вход: password=%s",
            "args": ("test-password",),
        }
    )
    output = handler.format(record)
    assert "test-password" not in output
    assert _metric(client, "warehouse_log_secrets_redacted_total") == before + 1
