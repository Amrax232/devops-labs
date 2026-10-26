"""Проверка служебных маршрутов."""

import logging

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.db import get_db
from app.main import app


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_reports_database(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_readyz_without_database_is_503(client: TestClient) -> None:
    """Экземпляр без базы не готов: healthcheck и проверка релиза это видят."""

    class BrokenSession:
        def execute(self, *_args: object) -> None:
            raise ConnectionError("база недоступна")

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = client.get("/readyz")
    finally:
        app.dependency_overrides.pop(get_db)
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}


def test_version_reports_release(anonymous_client: TestClient) -> None:
    """/version открыт без входа и называет версию и коммит образа."""
    response = anonymous_client.get("/version")
    assert response.status_code == 200
    assert response.json() == {
        "version": __version__,
        "revision": "test-revision",
        "environment": "test",
        "instance": "test-instance",
    }


def test_root_returns_service_info(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["version"] == __version__


def test_healthz_reports_instance(client: TestClient) -> None:
    assert client.get("/healthz").json()["instance"] == "test-instance"


@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        ("GET", "/", 200),
        ("GET", "/api/v1/units", 200),
        ("GET", "/api/v1/materials/999999", 404),
        ("POST", "/api/v1/units", 401),
    ],
)
def test_every_response_names_instance(
    anonymous_client: TestClient, method: str, path: str, expected_status: int
) -> None:
    """Балансировщик и пользователь видят, какой экземпляр обработал запрос,
    в том числе в ответах с ошибкой."""
    response = anonymous_client.request(method, path, json={"code": "kg", "name": "Килограмм"})
    assert response.status_code == expected_status
    assert response.headers["X-Instance-Id"] == "test-instance"


def test_shutdown_closes_database_connections(
    clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    """При остановке (SIGTERM → lifespan shutdown) пул соединений закрывается."""
    with caplog.at_level(logging.INFO, logger="app.main"), TestClient(app) as test_client:
        assert test_client.get("/readyz").status_code == 200
        assert "test-instance запущен" in caplog.text
        assert "остановлен" not in caplog.text
    assert "test-instance остановлен: соединения с БД закрыты" in caplog.text
