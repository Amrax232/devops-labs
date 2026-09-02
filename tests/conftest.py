"""Общие фикстуры тестов.

Тесты выполняются на отдельной SQLite-базе: они не требуют запущенного
PostgreSQL и поэтому проходят на любой машине командой `make test`.
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_DB = Path(tempfile.gettempdir()) / "warehouse_test.sqlite3"
# Переменные окружения выставляются ДО импорта приложения: конфигурация читается при импорте.
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB}"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    """Каждый тест начинается с пустой схемы."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client() -> Iterator[TestClient]:
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
