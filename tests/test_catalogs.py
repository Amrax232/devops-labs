"""Справочники: единицы измерения, материалы, поставщики."""

from fastapi.testclient import TestClient


def test_unit_code_is_unique(client: TestClient, unit_id: int) -> None:
    response = client.post("/api/v1/units", json={"code": "kg", "name": "Килограмм"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_material_requires_existing_unit(client: TestClient) -> None:
    response = client.post(
        "/api/v1/materials",
        json={"sku": "MAT-999", "name": "Гайка", "unit_id": 4242},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_material_sku_is_unique(client: TestClient, unit_id: int, material_id: int) -> None:
    response = client.post(
        "/api/v1/materials",
        json={"sku": "MAT-001", "name": "Другой болт", "unit_id": unit_id},
    )
    assert response.status_code == 409


def test_new_material_has_zero_quantity(client: TestClient, material_id: int) -> None:
    body = client.get(f"/api/v1/materials/{material_id}").json()
    assert float(body["quantity"]) == 0.0
    assert body["unit"]["code"] == "kg"


def test_unit_in_use_cannot_be_deleted(client: TestClient, unit_id: int, material_id: int) -> None:
    response = client.delete(f"/api/v1/units/{unit_id}")
    assert response.status_code == 409


def test_supplier_inn_is_validated(client: TestClient) -> None:
    response = client.post("/api/v1/suppliers", json={"name": "ООО Тест", "inn": "12345"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_supplier_inn_is_unique(client: TestClient, supplier_id: int) -> None:
    response = client.post("/api/v1/suppliers", json={"name": "ООО Копия", "inn": "7701234567"})
    assert response.status_code == 409


def test_supplier_can_be_deactivated(client: TestClient, supplier_id: int) -> None:
    response = client.patch(f"/api/v1/suppliers/{supplier_id}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert client.get("/api/v1/suppliers?only_active=true").json() == []


def test_supplier_search_by_name_and_inn(client: TestClient, supplier_id: int) -> None:
    """Поиск по подстроке в названии и ИНН, без учёта регистра."""
    client.post(
        "/api/v1/suppliers",
        json={"name": "АО Крепёж", "inn": "7809998877", "email": "info@krepezh.example"},
    )

    by_name = client.get("/api/v1/suppliers?q=Метизы").json()
    by_inn = client.get("/api/v1/suppliers?q=780999").json()
    by_case = client.get("/api/v1/suppliers?q=метизы").json()

    assert len(by_name) == 1 and by_name[0]["inn"] == "7701234567"
    assert len(by_inn) == 1 and by_inn[0]["name"] == "АО Крепёж"
    assert len(by_case) == 1
    assert client.get("/api/v1/suppliers?q=Трубы").json() == []


def test_supplier_search_combines_with_active_filter(
    client: TestClient, supplier_id: int
) -> None:
    """Поиск и фильтр активности работают вместе."""
    client.patch(f"/api/v1/suppliers/{supplier_id}", json={"is_active": False})

    assert len(client.get("/api/v1/suppliers?q=Метизы").json()) == 1
    assert client.get("/api/v1/suppliers?q=Метизы&only_active=true").json() == []


def test_material_search_by_name_and_sku(client: TestClient, material_id: int) -> None:
    assert len(client.get("/api/v1/materials?q=Болт").json()) == 1
    assert len(client.get("/api/v1/materials?q=mat-001").json()) == 1
    assert client.get("/api/v1/materials?q=труба").json() == []