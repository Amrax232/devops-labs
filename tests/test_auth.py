"""Доступ к API по логину и паролю (HTTP Basic)."""

from fastapi.testclient import TestClient

from tests.conftest import AUTH


def test_data_requires_credentials(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/v1/materials")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    # заголовок заставляет браузер показать окно ввода логина и пароля
    assert response.headers["www-authenticate"].startswith("Basic")


def test_wrong_password_is_rejected(anonymous_client: TestClient) -> None:
    anonymous_client.auth = (AUTH[0], "wrong-password")
    response = anonymous_client.get("/api/v1/materials")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_unknown_user_is_rejected(anonymous_client: TestClient) -> None:
    anonymous_client.auth = ("ghost", AUTH[1])
    assert anonymous_client.get("/api/v1/materials").status_code == 401


def test_correct_credentials_give_access(client: TestClient) -> None:
    assert client.get("/api/v1/materials").status_code == 200
    assert client.get("/api/v1/reports/stock").status_code == 200


def test_health_stays_public(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/healthz").status_code == 200
    assert anonymous_client.get("/readyz").status_code == 200
    assert anonymous_client.get("/").status_code == 200


def test_write_operations_are_protected(anonymous_client: TestClient) -> None:
    response = anonymous_client.post(
        "/api/v1/units", json={"code": "kg", "name": "Килограмм"}
    )
    assert response.status_code == 401
