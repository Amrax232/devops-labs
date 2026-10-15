"""Поступления: главное правило предметной области."""

from decimal import Decimal

from fastapi.testclient import TestClient


def _create_receipt(client: TestClient, supplier_id: int, material_id: int, number: str = "ПН-1"):
    return client.post(
        "/api/v1/receipts",
        json={
            "number": number,
            "supplier_id": supplier_id,
            "received_at": "2026-09-01",
            "items": [{"material_id": material_id, "quantity": "10.5", "price": "25.50"}],
        },
    )


def test_receipt_is_created_as_draft(client: TestClient, supplier_id: int, material_id: int):
    response = _create_receipt(client, supplier_id, material_id)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert len(body["items"]) == 1
    assert Decimal(str(body["total_amount"])) == Decimal("10.5") * Decimal("25.50")


def test_posting_increases_material_quantity(
    client: TestClient, supplier_id: int, material_id: int
):
    receipt_id = _create_receipt(client, supplier_id, material_id).json()["id"]

    response = client.post(f"/api/v1/receipts/{receipt_id}/post")
    assert response.status_code == 200
    assert response.json()["status"] == "posted"
    assert response.json()["posted_at"] is not None

    material = client.get(f"/api/v1/materials/{material_id}").json()
    assert Decimal(str(material["quantity"])) == Decimal("10.5")


def test_posted_receipt_cannot_be_posted_twice(
    client: TestClient, supplier_id: int, material_id: int
):
    receipt_id = _create_receipt(client, supplier_id, material_id).json()["id"]
    client.post(f"/api/v1/receipts/{receipt_id}/post")

    response = client.post(f"/api/v1/receipts/{receipt_id}/post")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "business_rule_violated"

    # остаток не изменился повторно
    material = client.get(f"/api/v1/materials/{material_id}").json()
    assert Decimal(str(material["quantity"])) == Decimal("10.5")


def test_posted_receipt_is_read_only(client: TestClient, supplier_id: int, material_id: int):
    receipt_id = _create_receipt(client, supplier_id, material_id).json()["id"]
    client.post(f"/api/v1/receipts/{receipt_id}/post")

    added = client.post(
        f"/api/v1/receipts/{receipt_id}/items",
        json={"material_id": material_id, "quantity": "1"},
    )
    assert added.status_code == 422
    assert client.delete(f"/api/v1/receipts/{receipt_id}").status_code == 422


def test_empty_receipt_cannot_be_posted(client: TestClient, supplier_id: int):
    receipt_id = client.post(
        "/api/v1/receipts",
        json={"number": "ПН-2", "supplier_id": supplier_id, "received_at": "2026-09-01"},
    ).json()["id"]

    response = client.post(f"/api/v1/receipts/{receipt_id}/post")
    assert response.status_code == 422


def test_receipt_number_is_unique(client: TestClient, supplier_id: int, material_id: int):
    _create_receipt(client, supplier_id, material_id)
    response = _create_receipt(client, supplier_id, material_id)
    assert response.status_code == 409


def test_material_cannot_repeat_in_one_receipt(
    client: TestClient, supplier_id: int, material_id: int
):
    response = client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-3",
            "supplier_id": supplier_id,
            "received_at": "2026-09-01",
            "items": [
                {"material_id": material_id, "quantity": "1"},
                {"material_id": material_id, "quantity": "2"},
            ],
        },
    )
    assert response.status_code == 422


def test_quantity_must_be_positive(client: TestClient, supplier_id: int, material_id: int):
    response = client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-4",
            "supplier_id": supplier_id,
            "received_at": "2026-09-01",
            "items": [{"material_id": material_id, "quantity": "0"}],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_receipt_requires_existing_supplier(client: TestClient, material_id: int):
    response = client.post(
        "/api/v1/receipts",
        json={"number": "ПН-5", "supplier_id": 777, "received_at": "2026-09-01"},
    )
    assert response.status_code == 404


def test_inactive_supplier_cannot_receive_goods(client: TestClient, supplier_id: int):
    client.patch(f"/api/v1/suppliers/{supplier_id}", json={"is_active": False})
    response = client.post(
        "/api/v1/receipts",
        json={"number": "ПН-6", "supplier_id": supplier_id, "received_at": "2026-09-01"},
    )
    assert response.status_code == 422


def test_draft_can_be_edited_and_deleted(client: TestClient, supplier_id: int, material_id: int):
    receipt_id = client.post(
        "/api/v1/receipts",
        json={"number": "ПН-7", "supplier_id": supplier_id, "received_at": "2026-09-01"},
    ).json()["id"]

    added = client.post(
        f"/api/v1/receipts/{receipt_id}/items",
        json={"material_id": material_id, "quantity": "3", "price": "10"},
    )
    assert added.status_code == 201
    item_id = added.json()["items"][0]["id"]

    removed = client.delete(f"/api/v1/receipts/{receipt_id}/items/{item_id}")
    assert removed.status_code == 200
    assert removed.json()["items"] == []

    assert client.delete(f"/api/v1/receipts/{receipt_id}").status_code == 204
    assert client.get(f"/api/v1/receipts/{receipt_id}").status_code == 404


def test_supplier_with_receipts_cannot_be_deleted(
    client: TestClient, supplier_id: int, material_id: int
):
    _create_receipt(client, supplier_id, material_id, number="ПН-8")
    assert client.delete(f"/api/v1/suppliers/{supplier_id}").status_code == 409


def test_material_with_receipts_cannot_be_deleted(
    client: TestClient, supplier_id: int, material_id: int
):
    _create_receipt(client, supplier_id, material_id, number="ПН-9")
    assert client.delete(f"/api/v1/materials/{material_id}").status_code == 409
