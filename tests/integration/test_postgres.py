"""Работа приложения с настоящей базой PostgreSQL.

Здесь проверяется то, что нельзя честно проверить на SQLite: ограничения
целостности самой СУБД, каскадное удаление и поведение при одновременных
запросах.
"""

import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.integration.conftest import AUTH


def _insert_material(engine: Engine, sku: str = "MAT-001") -> int:
    with engine.begin() as connection:
        unit_id = connection.execute(
            text("INSERT INTO units (code, name) VALUES ('pcs', 'Штука') RETURNING id")
        ).scalar_one()
        return connection.execute(
            text(
                "INSERT INTO materials (sku, name, unit_id) "
                "VALUES (:sku, 'Болт', :unit_id) RETURNING id"
            ),
            {"sku": sku, "unit_id": unit_id},
        ).scalar_one()


# ------------------------------------------------ ограничения на уровне базы данных
def test_database_rejects_negative_stock(migrated_engine: Engine) -> None:
    """Последний рубеж правила «остаток не уходит в минус» — CHECK в СУБД."""
    material_id = _insert_material(migrated_engine)

    with pytest.raises(IntegrityError, match="ck_materials_quantity_non_negative"):
        with migrated_engine.begin() as connection:
            connection.execute(
                text("UPDATE materials SET quantity = -1 WHERE id = :id"), {"id": material_id}
            )


def test_database_rejects_duplicate_sku(migrated_engine: Engine) -> None:
    _insert_material(migrated_engine, "MAT-DUP")

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO materials (sku, name, unit_id) "
                    "VALUES ('MAT-DUP', 'Копия', (SELECT id FROM units LIMIT 1))"
                )
            )


def test_database_rejects_non_positive_write_off(migrated_engine: Engine) -> None:
    material_id = _insert_material(migrated_engine)

    with pytest.raises(IntegrityError, match="ck_write_offs_quantity_positive"):
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO write_offs (material_id, quantity, reason) "
                    "VALUES (:id, 0, 'тест')"
                ),
                {"id": material_id},
            )


def test_deleting_receipt_removes_its_items(migrated_engine: Engine) -> None:
    material_id = _insert_material(migrated_engine)
    with migrated_engine.begin() as connection:
        supplier_id = connection.execute(
            text("INSERT INTO suppliers (name, inn) VALUES ('ООО Тест', '7701234567') RETURNING id")
        ).scalar_one()
        receipt_id = connection.execute(
            text(
                "INSERT INTO receipts (number, supplier_id, received_at) "
                "VALUES ('ПН-1', :s, '2026-10-01') RETURNING id"
            ),
            {"s": supplier_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO receipt_items (receipt_id, material_id, quantity, price) "
                "VALUES (:r, :m, 5, 10)"
            ),
            {"r": receipt_id, "m": material_id},
        )
        connection.execute(text("DELETE FROM receipts WHERE id = :r"), {"r": receipt_id})
        left = connection.execute(text("SELECT count(*) FROM receipt_items")).scalar_one()

    assert left == 0


# ------------------------------------------------------- приложение на PostgreSQL
def test_full_flow_on_postgresql(pg_client: TestClient) -> None:
    unit = pg_client.post("/api/v1/units", json={"code": "kg", "name": "Килограмм"}).json()
    supplier = pg_client.post(
        "/api/v1/suppliers",
        json={"name": "ООО Метизы", "inn": "7701234567", "phone": "+7 495 123-45-67"},
    ).json()
    material = pg_client.post(
        "/api/v1/materials",
        json={"sku": "MAT-001", "name": "Болт", "unit_id": unit["id"], "location": "A-01"},
    ).json()
    receipt = pg_client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-0001",
            "supplier_id": supplier["id"],
            "received_at": "2026-10-01",
            "items": [{"material_id": material["id"], "quantity": "100", "price": "12.30"}],
        },
    ).json()

    assert pg_client.post(f"/api/v1/receipts/{receipt['id']}/post").status_code == 200
    assert pg_client.post(f"/api/v1/receipts/{receipt['id']}/post").status_code == 422

    write_off = pg_client.post(
        f"/api/v1/materials/{material['id']}/write-offs",
        json={"quantity": "25.5", "reason": "Брак"},
    )
    assert write_off.status_code == 201

    stock = pg_client.get("/api/v1/reports/stock").json()["rows"][0]
    assert Decimal(str(stock["quantity"])) == Decimal("74.5")

    totals = pg_client.get("/api/v1/reports/receipts").json()
    assert Decimal(str(totals["total_amount"])) == Decimal("1230.00")
    assert pg_client.get("/readyz").json() == {"status": "ok", "database": "ok"}


def test_concurrent_write_offs_do_not_overdraw_stock(pg_client: TestClient) -> None:
    """Два одновременных списания по 60 из остатка 100: пройти может только одно."""
    unit = pg_client.post("/api/v1/units", json={"code": "pcs", "name": "Штука"}).json()
    supplier = pg_client.post(
        "/api/v1/suppliers", json={"name": "ООО Тест", "inn": "7701234567"}
    ).json()
    material = pg_client.post(
        "/api/v1/materials", json={"sku": "MAT-C", "name": "Гайка", "unit_id": unit["id"]}
    ).json()
    receipt = pg_client.post(
        "/api/v1/receipts",
        json={
            "number": "ПН-C",
            "supplier_id": supplier["id"],
            "received_at": "2026-10-01",
            "items": [{"material_id": material["id"], "quantity": "100"}],
        },
    ).json()
    pg_client.post(f"/api/v1/receipts/{receipt['id']}/post")

    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def write_off() -> None:
        with TestClient(pg_client.app) as client:
            client.auth = AUTH
            barrier.wait()
            response = client.post(
                f"/api/v1/materials/{material['id']}/write-offs",
                json={"quantity": "60", "reason": "Параллельно"},
            )
            statuses.append(response.status_code)

    threads = [threading.Thread(target=write_off) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(statuses) == [201, 422]
    final = pg_client.get(f"/api/v1/materials/{material['id']}").json()
    assert Decimal(str(final["quantity"])) == Decimal("40")
