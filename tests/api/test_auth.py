"""Разграничение прав доступа.

Читать данные может любой, даже без входа. Добавлять, изменять и удалять —
только после входа по логину и паролю. Неверные логин или пароль отклоняются
при любом запросе, в том числе при чтении.
"""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app
from tests.api.conftest import AUTH

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _api_routes(methods: set[str]) -> list[tuple[str, str]]:
    """Все маршруты /api/ с указанными методами; параметры пути заменены на 1."""
    found = []
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/"):
            for method in sorted(route.methods & methods):
                found.append((method, re.sub(r"\{[^}]+\}", "1", route.path)))
    return found


# ------------------------------------------------------------ анонимный доступ
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/units",
        "/api/v1/suppliers",
        "/api/v1/materials",
        "/api/v1/receipts",
        "/api/v1/reports/stock",
        "/api/v1/reports/receipts",
    ],
)
def test_anonymous_user_can_read(anonymous_client: TestClient, path: str) -> None:
    assert anonymous_client.get(path).status_code == 200


def test_anonymous_user_sees_existing_data(
    client: TestClient, anonymous_client: TestClient, material_id: int
) -> None:
    response = anonymous_client.get(f"/api/v1/materials/{material_id}")

    assert response.status_code == 200
    assert response.json()["sku"] == "MAT-001"


@pytest.mark.parametrize(("method", "path"), _api_routes({"GET"}))
def test_no_read_route_requires_credentials(
    anonymous_client: TestClient, method: str, path: str
) -> None:
    """Ни один маршрут чтения не требует входа (404 для несуществующего id — нормально)."""
    assert anonymous_client.request(method, path).status_code != 401


@pytest.mark.parametrize(("method", "path"), _api_routes(WRITE_METHODS))
def test_every_write_route_requires_credentials(
    anonymous_client: TestClient, method: str, path: str
) -> None:
    """Проверяются ВСЕ маршруты изменения, найденные в приложении.

    Если кто-то добавит новый маршрут и забудет закрыть его, этот тест упадёт.
    """
    response = anonymous_client.request(method, path, json={})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    # заголовок заставляет браузер показать окно ввода логина и пароля
    assert response.headers["www-authenticate"].startswith("Basic")


def test_all_write_routes_are_found() -> None:
    """Защита от пустого списка: если поиск маршрутов сломается, тест выше ничего не проверит."""
    assert len(_api_routes(WRITE_METHODS)) >= 14


def test_anonymous_attempt_does_not_change_data(
    client: TestClient, anonymous_client: TestClient, unit_id: int
) -> None:
    anonymous_client.delete(f"/api/v1/units/{unit_id}")
    anonymous_client.post("/api/v1/units", json={"code": "pcs", "name": "Штука"})

    units = client.get("/api/v1/units").json()
    assert [unit["code"] for unit in units] == ["kg"]


# -------------------------------------------------------- проверка учётных данных
def test_correct_credentials_allow_changes(client: TestClient) -> None:
    assert client.post("/api/v1/units", json={"code": "kg", "name": "Кг"}).status_code == 201


def test_wrong_password_is_rejected_even_for_reading(anonymous_client: TestClient) -> None:
    anonymous_client.auth = (AUTH[0], "wrong-password")

    response = anonymous_client.get("/api/v1/materials")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Неверный логин или пароль"


def test_unknown_user_is_rejected(anonymous_client: TestClient) -> None:
    anonymous_client.auth = ("ghost", AUTH[1])

    created = anonymous_client.post("/api/v1/units", json={"code": "x", "name": "y"})

    assert created.status_code == 401
    assert anonymous_client.get("/api/v1/units").status_code == 401


def test_health_stays_public(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/healthz").status_code == 200
    assert anonymous_client.get("/readyz").status_code == 200
    assert anonymous_client.get("/").status_code == 200
