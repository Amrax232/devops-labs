"""Правила предметной области «Складской учёт».

Здесь собрана вся содержательная логика: маршруты (routers) только принимают
запрос и вызывают функции этого модуля.

Основные правила:
1. Поступление создаётся в статусе `draft` и в этом статусе редактируется.
2. Провести (`post`) можно только черновик и только если в нём есть позиции.
   При проведении остатки материалов увеличиваются на количество из позиций.
3. Проведённый документ нельзя изменить, дополнить или удалить.
4. Нельзя удалить справочный объект, на который ссылаются другие записи.
5. Номер поступления, артикул материала, код единицы и ИНН поставщика уникальны.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import (
    Material,
    Receipt,
    ReceiptItem,
    ReceiptStatus,
    Supplier,
    Unit,
    utcnow,
)
from app.schemas import (
    MaterialCreate,
    MaterialUpdate,
    ReceiptCreate,
    ReceiptItemCreate,
    ReceiptsReport,
    StockReport,
    StockRow,
    SupplierCreate,
    SupplierSummaryRow,
    SupplierUpdate,
    UnitCreate,
)


# --------------------------------------------------------------------- вспомогательное
def _get_or_404(db: Session, model: type, obj_id: int, title: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise NotFoundError(f"{title} с id={obj_id} не найден", {"id": obj_id})
    return obj


def _ensure_free(db: Session, model: type, field: str, value: str, title: str) -> None:
    exists = db.scalar(select(model.id).where(getattr(model, field) == value))
    if exists is not None:
        raise ConflictError(
            f"{title} «{value}» уже используется",
            {"field": field, "value": value},
        )


# ------------------------------------------------------------------- единицы измерения
def create_unit(db: Session, data: UnitCreate) -> Unit:
    _ensure_free(db, Unit, "code", data.code, "Код единицы измерения")
    unit = Unit(code=data.code, name=data.name)
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit


def list_units(db: Session) -> list[Unit]:
    return list(db.scalars(select(Unit).order_by(Unit.code)))


def delete_unit(db: Session, unit_id: int) -> None:
    unit = _get_or_404(db, Unit, unit_id, "Единица измерения")
    used = db.scalar(select(func.count(Material.id)).where(Material.unit_id == unit_id))
    if used:
        raise ConflictError(
            "Единица измерения используется материалами и не может быть удалена",
            {"materials": used},
        )
    db.delete(unit)
    db.commit()


# ------------------------------------------------------------------------- поставщики
def create_supplier(db: Session, data: SupplierCreate) -> Supplier:
    _ensure_free(db, Supplier, "inn", data.inn, "ИНН")
    supplier = Supplier(**data.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


def list_suppliers(db: Session, *, only_active: bool = False) -> list[Supplier]:
    stmt = select(Supplier).order_by(Supplier.name)
    if only_active:
        stmt = stmt.where(Supplier.is_active.is_(True))
    return list(db.scalars(stmt))


def get_supplier(db: Session, supplier_id: int) -> Supplier:
    return _get_or_404(db, Supplier, supplier_id, "Поставщик")


def update_supplier(db: Session, supplier_id: int, data: SupplierUpdate) -> Supplier:
    supplier = get_supplier(db, supplier_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    db.commit()
    db.refresh(supplier)
    return supplier


def delete_supplier(db: Session, supplier_id: int) -> None:
    supplier = get_supplier(db, supplier_id)
    used = db.scalar(select(func.count(Receipt.id)).where(Receipt.supplier_id == supplier_id))
    if used:
        raise ConflictError(
            "У поставщика есть поступления, удаление запрещено. "
            "Деактивируйте поставщика (is_active=false)",
            {"receipts": used},
        )
    db.delete(supplier)
    db.commit()


# -------------------------------------------------------------------------- материалы
def create_material(db: Session, data: MaterialCreate) -> Material:
    _ensure_free(db, Material, "sku", data.sku, "Артикул")
    _get_or_404(db, Unit, data.unit_id, "Единица измерения")
    material = Material(
        sku=data.sku,
        name=data.name,
        unit_id=data.unit_id,
        min_stock=data.min_stock,
        quantity=Decimal("0"),
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


def list_materials(
    db: Session, *, query: str | None = None, below_min: bool = False
) -> list[Material]:
    stmt = select(Material).options(selectinload(Material.unit)).order_by(Material.sku)
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(Material.name.ilike(pattern) | Material.sku.ilike(pattern))
    if below_min:
        stmt = stmt.where(Material.quantity < Material.min_stock)
    return list(db.scalars(stmt))


def get_material(db: Session, material_id: int) -> Material:
    return _get_or_404(db, Material, material_id, "Материал")


def update_material(db: Session, material_id: int, data: MaterialUpdate) -> Material:
    material = get_material(db, material_id)
    payload = data.model_dump(exclude_unset=True)
    if "unit_id" in payload and payload["unit_id"] is not None:
        _get_or_404(db, Unit, payload["unit_id"], "Единица измерения")
    for field, value in payload.items():
        setattr(material, field, value)
    db.commit()
    db.refresh(material)
    return material


def delete_material(db: Session, material_id: int) -> None:
    material = get_material(db, material_id)
    used = db.scalar(
        select(func.count(ReceiptItem.id)).where(ReceiptItem.material_id == material_id)
    )
    if used:
        raise ConflictError(
            "Материал участвует в поступлениях и не может быть удалён",
            {"receipt_items": used},
        )
    db.delete(material)
    db.commit()


# ------------------------------------------------------------------------ поступления
def _load_receipt(db: Session, receipt_id: int) -> Receipt:
    receipt = db.scalar(
        select(Receipt).options(selectinload(Receipt.items)).where(Receipt.id == receipt_id)
    )
    if receipt is None:
        raise NotFoundError(f"Поступление с id={receipt_id} не найдено", {"id": receipt_id})
    return receipt


def _ensure_draft(receipt: Receipt) -> None:
    if receipt.status is not ReceiptStatus.DRAFT:
        raise BusinessRuleError(
            "Проведённое поступление изменить нельзя",
            {"receipt_id": receipt.id, "status": receipt.status.value},
        )


def create_receipt(db: Session, data: ReceiptCreate) -> Receipt:
    _ensure_free(db, Receipt, "number", data.number, "Номер поступления")
    supplier = get_supplier(db, data.supplier_id)
    if not supplier.is_active:
        raise BusinessRuleError(
            "Поставщик деактивирован, оформить поступление нельзя",
            {"supplier_id": supplier.id},
        )

    seen: set[int] = set()
    items: list[ReceiptItem] = []
    for item in data.items:
        if item.material_id in seen:
            raise BusinessRuleError(
                "Материал встречается в документе дважды — объедините строки",
                {"material_id": item.material_id},
            )
        seen.add(item.material_id)
        _get_or_404(db, Material, item.material_id, "Материал")
        items.append(
            ReceiptItem(
                material_id=item.material_id,
                quantity=item.quantity,
                price=item.price,
            )
        )

    receipt = Receipt(
        number=data.number,
        supplier_id=data.supplier_id,
        received_at=data.received_at,
        status=ReceiptStatus.DRAFT,
        items=items,
    )
    db.add(receipt)
    db.commit()
    return _load_receipt(db, receipt.id)


def list_receipts(
    db: Session,
    *,
    supplier_id: int | None = None,
    status: ReceiptStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[Receipt]:
    stmt = (
        select(Receipt)
        .options(selectinload(Receipt.items))
        .order_by(Receipt.received_at.desc(), Receipt.id.desc())
    )
    if supplier_id is not None:
        stmt = stmt.where(Receipt.supplier_id == supplier_id)
    if status is not None:
        stmt = stmt.where(Receipt.status == status)
    if date_from is not None:
        stmt = stmt.where(Receipt.received_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Receipt.received_at <= date_to)
    return list(db.scalars(stmt))


def get_receipt(db: Session, receipt_id: int) -> Receipt:
    return _load_receipt(db, receipt_id)


def add_receipt_item(db: Session, receipt_id: int, data: ReceiptItemCreate) -> Receipt:
    receipt = _load_receipt(db, receipt_id)
    _ensure_draft(receipt)
    _get_or_404(db, Material, data.material_id, "Материал")
    if any(item.material_id == data.material_id for item in receipt.items):
        raise BusinessRuleError(
            "Материал уже есть в документе — измените существующую строку",
            {"material_id": data.material_id},
        )
    receipt.items.append(
        ReceiptItem(material_id=data.material_id, quantity=data.quantity, price=data.price)
    )
    db.commit()
    return _load_receipt(db, receipt_id)


def delete_receipt_item(db: Session, receipt_id: int, item_id: int) -> Receipt:
    receipt = _load_receipt(db, receipt_id)
    _ensure_draft(receipt)
    item = next((i for i in receipt.items if i.id == item_id), None)
    if item is None:
        raise NotFoundError(
            f"Строка с id={item_id} в поступлении не найдена",
            {"receipt_id": receipt_id, "item_id": item_id},
        )
    receipt.items.remove(item)
    db.commit()
    return _load_receipt(db, receipt_id)


def post_receipt(db: Session, receipt_id: int) -> Receipt:
    """Провести поступление: увеличить остатки материалов и закрыть документ."""
    receipt = _load_receipt(db, receipt_id)
    _ensure_draft(receipt)
    if not receipt.items:
        raise BusinessRuleError(
            "Нельзя провести поступление без позиций",
            {"receipt_id": receipt_id},
        )

    for item in receipt.items:
        material = _get_or_404(db, Material, item.material_id, "Материал")
        material.quantity = Decimal(str(material.quantity)) + Decimal(str(item.quantity))

    receipt.status = ReceiptStatus.POSTED
    receipt.posted_at = utcnow()
    db.commit()
    return _load_receipt(db, receipt_id)


def delete_receipt(db: Session, receipt_id: int) -> None:
    receipt = _load_receipt(db, receipt_id)
    _ensure_draft(receipt)
    db.delete(receipt)
    db.commit()


# ----------------------------------------------------------------------------- отчёты
def stock_report(db: Session, *, only_below_min: bool = False) -> StockReport:
    stmt = (
        select(Material, Unit.code)
        .join(Unit, Material.unit_id == Unit.id)
        .order_by(Material.sku)
    )
    if only_below_min:
        stmt = stmt.where(Material.quantity < Material.min_stock)

    rows = [
        StockRow(
            material_id=material.id,
            sku=material.sku,
            name=material.name,
            unit_code=unit_code,
            quantity=material.quantity,
            min_stock=material.min_stock,
            below_min=Decimal(str(material.quantity)) < Decimal(str(material.min_stock)),
        )
        for material, unit_code in db.execute(stmt).all()
    ]
    return StockReport(rows=rows, positions=len(rows))


def receipts_report(
    db: Session, *, date_from: date | None = None, date_to: date | None = None
) -> ReceiptsReport:
    """Сводка проведённых поступлений по поставщикам за период."""
    amount = func.coalesce(func.sum(ReceiptItem.quantity * ReceiptItem.price), 0)
    stmt = (
        select(
            Supplier.id,
            Supplier.name,
            func.count(func.distinct(Receipt.id)),
            amount,
        )
        .join(Receipt, Receipt.supplier_id == Supplier.id)
        .join(ReceiptItem, ReceiptItem.receipt_id == Receipt.id)
        .where(Receipt.status == ReceiptStatus.POSTED)
        .group_by(Supplier.id, Supplier.name)
        .order_by(Supplier.name)
    )
    if date_from is not None:
        stmt = stmt.where(Receipt.received_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Receipt.received_at <= date_to)

    rows = [
        SupplierSummaryRow(
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            receipts_count=count,
            total_amount=Decimal(str(total)),
        )
        for supplier_id, supplier_name, count, total in db.execute(stmt).all()
    ]
    return ReceiptsReport(
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        total_amount=sum((r.total_amount for r in rows), Decimal("0")),
    )
