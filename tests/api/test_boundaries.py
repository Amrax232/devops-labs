"""Ошибочные данные и граничные значения на уровне HTTP API.

Каждый параметр проверяется на границе допустимого: последнее допустимое
значение принимается, первое недопустимое — отклоняется с понятным кодом ошибки.
"""

import pytest
from fastapi.testclient import TestClient


def _error_code(response) -> str:
    return response.json()["error"]["code"]


# ------------------------------------------------------------------- поставщики
@pytest.mark.parametrize(
    ("inn", "status"),
    [
        ("770123456", 422),
        ("7701234567", 201),
        ("77012345678", 422),
        ("770123456789", 201),
        ("7701234567890", 422),
        ("77012345ab", 422),
    ],
)
def test_supplier_inn_boundaries(client: TestClient, inn: str, status: int) -> None:
    response = client.post("/api/v1/suppliers", json={"name": "ООО Тест", "inn": inn})
    assert response.status_code == status


@pytest.mark.parametrize(
    ("phone", "status"),
    [
        ("+7 495 123-45-67", 201),
        ("(495) 1234567", 201),
        ("12345", 201),  # минимальная длина
        ("1234", 422),  # короче минимума
        ("+7 495 ABC", 422),  # буквы
        ("1" * 32, 201),  # максимальная длина
        ("1" * 33, 422),
    ],
)
def test_supplier_phone_boundaries(client: TestClient, phone: str, status: int) -> None:
    response = client.post(
        "/api/v1/suppliers", json={"name": "ООО Тест", "inn": "7701234567", "phone": phone}
    )
    assert response.status_code == status


def test_supplier_name_cannot_be_empty(client: TestClient) -> None:
    response = client.post("/api/v1/suppliers", json={"name": "", "inn": "7701234567"})
    assert response.status_code == 422
    assert _error_code(response) == "validation_error"


# -------------------------------------------------------------------- материалы
@pytest.mark.parametrize(("length", "status"), [(1, 201), (32, 201), (33, 422)])
def test_material_sku_length(client: TestClient, unit_id: int, length: int, status: int) -> None:
    response = client.post(
        "/api/v1/materials",
        json={"sku": "S" * length, "name": "Гайка", "unit_id": unit_id},
    )
    assert response.status_code == status


@pytest.mark.parametrize(
    ("min_stock", "status"),
    [("0", 201), ("0.001", 201), ("-0.001", 422), ("0.0001", 422), ("abc", 422)],
)
def test_material_min_stock_boundaries(
    client: TestClient, unit_id: int, min_stock: str, status: int
) -> None:
    response = client.post(
        "/api/v1/materials",
        json={"sku": "MAT-B", "name": "Гайка", "unit_id": unit_id, "min_stock": min_stock},
    )
    assert response.status_code == status


def test_material_location_defaults_to_main(client: TestClient, unit_id: int) -> None:
    response = client.post(
        "/api/v1/materials", json={"sku": "MAT-L", "name": "Шайба", "unit_id": unit_id}
    )
    assert response.json()["location"] == "MAIN"


def test_material_location_can_be_changed(client: TestClient, material_id: int) -> None:
    response = client.patch(f"/api/v1/materials/{material_id}", json={"location": "A-01-03"})
    assert response.json()["location"] == "A-01-03"


# ------------------------------------------------------------------ поступления
@pytest.mark.parametrize(
    ("quantity", "status"),
    [
        ("0", 422),
        ("-1", 422),
        ("0.001", 201),  # наименьшее допустимое количество при точности 3 знака
        ("0.0001", 422),  # четвёртый знак не хранится — значение отклоняется, а не округляется
        ("99999999999.999", 201),  # максимум NUMERIC(14,3)
        ("999999999999.999", 422),  # 15 значащих цифр — не помещается
    ],
)
def test_receipt_quantity_boundaries(
    client: TestClient, supplier_id: int, material_id: int, quantity: str, status: int
) -> None:
    response = client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-B",
            "supplier_id": supplier_id,
            "received_at": "2026-10-01",
            "items": [{"material_id": material_id, "quantity": quantity}],
        },
    )
    assert response.status_code == status


@pytest.mark.parametrize(("price", "status"), [("0", 201), ("0.01", 201), ("-0.01", 422)])
def test_receipt_price_boundaries(
    client: TestClient, supplier_id: int, material_id: int, price: str, status: int
) -> None:
    response = client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-P",
            "supplier_id": supplier_id,
            "received_at": "2026-10-01",
            "items": [{"material_id": material_id, "quantity": "1", "price": price}],
        },
    )
    assert response.status_code == status


@pytest.mark.parametrize("received_at", ["2026-13-01", "2026-02-30", "вчера", ""])
def test_receipt_invalid_date(client: TestClient, supplier_id: int, received_at: str) -> None:
    response = client.post(
        "/api/v1/receipts",
        json={"number": "ПН-D", "supplier_id": supplier_id, "received_at": received_at},
    )
    assert response.status_code == 422
    assert _error_code(response) == "validation_error"


def test_receipt_requires_mandatory_fields(client: TestClient) -> None:
    response = client.post("/api/v1/receipts", json={"number": "ПН-E"})

    assert response.status_code == 422
    missing = {tuple(field["loc"])[-1] for field in response.json()["error"]["details"]["fields"]}
    assert {"supplier_id", "received_at"} <= missing


def test_malformed_json_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/units", content="{не json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert _error_code(response) == "validation_error"


# ----------------------------------------------------------------------- списания
@pytest.mark.parametrize(
    ("reason", "status"), [("Бр", 422), ("Брк", 201), ("Б" * 255, 201), ("Б" * 256, 422)]
)
def test_write_off_reason_length(
    client: TestClient, stocked_material_id: int, reason: str, status: int
) -> None:
    response = client.post(
        f"/api/v1/materials/{stocked_material_id}/write-offs",
        json={"quantity": "1", "reason": reason},
    )
    assert response.status_code == status


# ------------------------------------------------------------------------- отчёты
@pytest.mark.parametrize(("limit", "status"), [(0, 422), (1, 200), (500, 200), (501, 422)])
def test_stock_report_limit_boundaries(client: TestClient, limit: int, status: int) -> None:
    assert client.get(f"/api/v1/reports/stock?limit={limit}").status_code == status


# --------------------------------------------------------------------- не найдено
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/materials/999",
        "/api/v1/suppliers/999",
        "/api/v1/receipts/999",
        "/api/v1/materials/999/write-offs",
    ],
)
def test_unknown_objects_return_404(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert _error_code(response) == "not_found"
