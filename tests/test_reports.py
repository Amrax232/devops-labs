"""Отчёты по складу."""

from decimal import Decimal

from fastapi.testclient import TestClient


def test_stock_report_marks_positions_below_minimum(
    client: TestClient, supplier_id: int, material_id: int
):
    report = client.get("/api/v1/reports/stock").json()
    assert report["positions"] == 1
    assert report["rows"][0]["below_min"] is True  # остаток 0 при минимуме 50

    receipt_id = client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-100",
            "supplier_id": supplier_id,
            "received_at": "2026-09-05",
            "items": [{"material_id": material_id, "quantity": "60", "price": "12.00"}],
        },
    ).json()["id"]
    client.post(f"/api/v1/receipts/{receipt_id}/post")

    report = client.get("/api/v1/reports/stock").json()
    assert report["rows"][0]["below_min"] is False
    assert client.get("/api/v1/reports/stock?below_min=true").json()["positions"] == 0


def test_receipts_report_counts_only_posted_documents(
    client: TestClient, supplier_id: int, material_id: int
):
    draft_id = client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-101",
            "supplier_id": supplier_id,
            "received_at": "2026-09-05",
            "items": [{"material_id": material_id, "quantity": "5", "price": "100.00"}],
        },
    ).json()["id"]

    empty = client.get("/api/v1/reports/receipts").json()
    assert empty["rows"] == []

    client.post(f"/api/v1/receipts/{draft_id}/post")
    report = client.get("/api/v1/reports/receipts").json()
    assert report["rows"][0]["receipts_count"] == 1
    assert Decimal(str(report["total_amount"])) == Decimal("500")


def test_receipts_report_respects_period(
    client: TestClient, supplier_id: int, material_id: int
):
    receipt_id = client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-102",
            "supplier_id": supplier_id,
            "received_at": "2026-09-05",
            "items": [{"material_id": material_id, "quantity": "5", "price": "100.00"}],
        },
    ).json()["id"]
    client.post(f"/api/v1/receipts/{receipt_id}/post")

    inside = client.get("/api/v1/reports/receipts?date_from=2026-09-01&date_to=2026-09-30").json()
    outside = client.get("/api/v1/reports/receipts?date_from=2026-10-01").json()
    assert inside["rows"][0]["receipts_count"] == 1
    assert outside["rows"] == []


def test_stock_report_can_be_sorted(client: TestClient, unit_id: int) -> None:
    """Сортировка отчёта по имени материала."""
    for sku, name in [("MAT-003", "Труба"), ("MAT-002", "Гайка")]:
        client.post(
            "/api/v1/materials",
            json={"sku": sku, "name": name, "unit_id": unit_id},
        )

    default_order = client.get("/api/v1/reports/stock").json()
    by_name = client.get("/api/v1/reports/stock?order_by=name").json()

    assert [r["sku"] for r in default_order["rows"]] == ["MAT-002", "MAT-003"]
    assert [r["name"] for r in by_name["rows"]] == ["Гайка", "Труба"]


def test_stock_report_rejects_unknown_order_field(client: TestClient) -> None:
    """Недопустимое поле сортировки возвращает business_rule_violated."""
    response = client.get("/api/v1/reports/stock?order_by=price")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "business_rule_violated"