"""Наполнение базы демонстрационными данными.

Запуск из корня проекта:  make seed   (или  .venv/bin/python -m scripts.seed)
Запуск через «-m» из корня проекта делает пакет app доступным для импорта.

Данные создаются через слой services, то есть по тем же правилам, что и через
API: остатки материалов меняются только проведением документа поступления.
Скрипт можно запускать повторно — уже существующие записи пропускаются.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.db import SessionLocal
from app.models import Material, Receipt, ReceiptStatus, Supplier, Unit
from app.schemas import (
    MaterialCreate,
    ReceiptCreate,
    ReceiptItemCreate,
    SupplierCreate,
    UnitCreate,
)

UNITS = [
    ("pcs", "Штука"),
    ("kg", "Килограмм"),
    ("m", "Метр"),
]

SUPPLIERS = [
    ('ООО "Метизы"', "7701234567", "sales@metiz.example"),
    ('АО "Крепёж"', "7809998877", "zakaz@krepezh.example"),
    ('ООО "СтальТорг"', "540112233445", None),
]

# артикул, наименование, код единицы, минимальный запас
MATERIALS = [
    ("MAT-001", "Болт М8х40", "pcs", "500"),
    ("MAT-002", "Гайка М8", "pcs", "500"),
    ("MAT-003", "Шайба 8", "pcs", "1000"),
    ("MAT-004", "Лента ФУМ", "m", "50"),
    ("MAT-005", "Электрод МР-3", "kg", "20"),
    ("MAT-006", "Труба ВГП 25", "m", "100"),
]

# номер, ИНН поставщика, дата, проводить ли, позиции (артикул, количество, цена)
RECEIPTS = [
    (
        "ПН-0001",
        "7701234567",
        date(2026, 9, 1),
        True,
        [("MAT-001", "1000", "12.30"), ("MAT-002", "800", "6.15")],
    ),
    (
        "ПН-0002",
        "7809998877",
        date(2026, 9, 10),
        True,
        [("MAT-003", "1500", "1.40"), ("MAT-005", "25", "180.00")],
    ),
    (
        "ПН-0003",
        "540112233445",
        date(2026, 9, 18),
        False,  # остаётся черновиком — видно разницу статусов
        [("MAT-006", "60", "410.00"), ("MAT-004", "30", "35.50")],
    ),
]


def seed_units(db: Session) -> dict[str, int]:
    ids: dict[str, int] = {}
    for code, name in UNITS:
        unit = db.scalar(select(Unit).where(Unit.code == code))
        if unit is None:
            unit = services.create_unit(db, UnitCreate(code=code, name=name))
            print(f"  + единица измерения {code}")
        ids[code] = unit.id
    return ids


def seed_suppliers(db: Session) -> dict[str, int]:
    ids: dict[str, int] = {}
    for name, inn, email in SUPPLIERS:
        supplier = db.scalar(select(Supplier).where(Supplier.inn == inn))
        if supplier is None:
            supplier = services.create_supplier(
                db, SupplierCreate(name=name, inn=inn, email=email)
            )
            print(f"  + поставщик {name}")
        ids[inn] = supplier.id
    return ids


def seed_materials(db: Session, unit_ids: dict[str, int]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for sku, name, unit_code, min_stock in MATERIALS:
        material = db.scalar(select(Material).where(Material.sku == sku))
        if material is None:
            material = services.create_material(
                db,
                MaterialCreate(
                    sku=sku,
                    name=name,
                    unit_id=unit_ids[unit_code],
                    min_stock=Decimal(min_stock),
                ),
            )
            print(f"  + материал {sku} {name}")
        ids[sku] = material.id
    return ids


def seed_receipts(
    db: Session, supplier_ids: dict[str, int], material_ids: dict[str, int]
) -> None:
    for number, inn, received_at, post, items in RECEIPTS:
        if db.scalar(select(Receipt).where(Receipt.number == number)) is not None:
            continue
        receipt = services.create_receipt(
            db,
            ReceiptCreate(
                number=number,
                supplier_id=supplier_ids[inn],
                received_at=received_at,
                items=[
                    ReceiptItemCreate(
                        material_id=material_ids[sku],
                        quantity=Decimal(quantity),
                        price=Decimal(price),
                    )
                    for sku, quantity, price in items
                ],
            ),
        )
        print(f"  + поступление {number} ({len(items)} строк)")
        if post:
            services.post_receipt(db, receipt.id)
            print("    проведено, остатки увеличены")


def main() -> None:
    print("Наполнение базы демонстрационными данными...")
    with SessionLocal() as db:
        unit_ids = seed_units(db)
        supplier_ids = seed_suppliers(db)
        material_ids = seed_materials(db, unit_ids)
        seed_receipts(db, supplier_ids, material_ids)

        posted = len(services.list_receipts(db, status=ReceiptStatus.POSTED))
        drafts = len(services.list_receipts(db, status=ReceiptStatus.DRAFT))
        print(
            f"Готово: {len(unit_ids)} единиц, {len(supplier_ids)} поставщиков, "
            f"{len(material_ids)} материалов, поступлений проведено {posted}, "
            f"черновиков {drafts}."
        )


if __name__ == "__main__":
    main()
