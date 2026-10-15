"""Фикстуры для тестов HTTP API.

Приложение работает с SQLite-базой из временного каталога (см. tests/conftest.py);
перед каждым тестом схема создаётся заново, поэтому тесты не зависят друг от
друга и от порядка запуска.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app

AUTH = ("tester", "test-password")


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    """Каждый тест начинается с пустой схемы."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(clean_database: None) -> Iterator[TestClient]:
    """Клиент с логином и паролем — используется большинством тестов."""
    with TestClient(app) as test_client:
        test_client.auth = AUTH
        yield test_client


@pytest.fixture
def anonymous_client(clean_database: None) -> Iterator[TestClient]:
    """Клиент без логина: для проверки, что данные закрыты."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def unit_id(client: TestClient) -> int:
    response = client.post("/api/v1/units", json={"code": "kg", "name": "Килограмм"})
    assert response.status_code == 201
    return response.json()["id"]


@pytest.fixture
def supplier_id(client: TestClient) -> int:
    response = client.post(
        "/api/v1/suppliers",
        json={"name": 'ООО "Метизы"', "inn": "7701234567", "email": "sales@metiz.example"},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.fixture
def material_id(client: TestClient, unit_id: int) -> int:
    response = client.post(
        "/api/v1/materials",
        json={"sku": "MAT-001", "name": "Болт М8х40", "unit_id": unit_id, "min_stock": "50"},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.fixture
def stocked_material_id(client: TestClient, supplier_id: int, material_id: int) -> int:
    """Материал с остатком 100 — после проведённого поступления."""
    receipt = client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-STOCK",
            "supplier_id": supplier_id,
            "received_at": "2026-10-01",
            "items": [{"material_id": material_id, "quantity": "100", "price": "10.00"}],
        },
    ).json()
    assert client.post(f"/api/v1/receipts/{receipt['id']}/post").status_code == 200
    return material_id
