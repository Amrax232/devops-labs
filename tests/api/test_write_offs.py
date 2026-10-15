"""Списание материалов — функция, добавленная в ЛР3 вместе с миграцией 0004."""

from decimal import Decimal

from fastapi.testclient import TestClient


def _stock(client: TestClient, material_id: int) -> Decimal:
    return Decimal(str(client.get(f"/api/v1/materials/{material_id}").json()["quantity"]))


def _write_off(client: TestClient, material_id: int, quantity: str, reason: str = "Брак"):
    return client.post(
        f"/api/v1/materials/{material_id}/write-offs",
        json={"quantity": quantity, "reason": reason},
    )


def test_write_off_decreases_stock(client: TestClient, stocked_material_id: int) -> None:
    response = _write_off(client, stocked_material_id, "30.5", "Порча при хранении")

    assert response.status_code == 201
    body = response.json()
    assert Decimal(str(body["quantity"])) == Decimal("30.5")
    assert body["reason"] == "Порча при хранении"
    assert _stock(client, stocked_material_id) == Decimal("69.5")


def test_whole_stock_can_be_written_off(client: TestClient, stocked_material_id: int) -> None:
    assert _write_off(client, stocked_material_id, "100").status_code == 201
    assert _stock(client, stocked_material_id) == Decimal("0")


def test_cannot_write_off_more_than_stock(client: TestClient, stocked_material_id: int) -> None:
    response = _write_off(client, stocked_material_id, "100.001")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "business_rule_violated"
    details = response.json()["error"]["details"]
    assert Decimal(details["stock"]) == Decimal("100")
    assert Decimal(details["requested"]) == Decimal("100.001")
    # остаток не изменился и запись о списании не создана
    assert _stock(client, stocked_material_id) == Decimal("100")
    assert client.get(f"/api/v1/materials/{stocked_material_id}/write-offs").json() == []


def test_cannot_write_off_from_empty_stock(client: TestClient, material_id: int) -> None:
    assert _write_off(client, material_id, "1").status_code == 422


def test_write_off_of_unknown_material(client: TestClient) -> None:
    assert _write_off(client, 4242, "1").status_code == 404


def test_write_off_history_is_newest_first(client: TestClient, stocked_material_id: int) -> None:
    _write_off(client, stocked_material_id, "1", "Первое")
    _write_off(client, stocked_material_id, "2", "Второе")

    history = client.get(f"/api/v1/materials/{stocked_material_id}/write-offs").json()

    assert [item["reason"] for item in history] == ["Второе", "Первое"]


def test_material_with_write_offs_cannot_be_deleted(
    client: TestClient, stocked_material_id: int
) -> None:
    _write_off(client, stocked_material_id, "1")
    response = client.delete(f"/api/v1/materials/{stocked_material_id}")

    assert response.status_code == 409
    assert response.json()["error"]["details"]["write_offs"] == 1


def test_write_off_requires_credentials(
    anonymous_client: TestClient,
) -> None:
    response = anonymous_client.post(
        "/api/v1/materials/1/write-offs", json={"quantity": "1", "reason": "Брак"}
    )
    assert response.status_code == 401
