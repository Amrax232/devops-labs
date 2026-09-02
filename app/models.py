"""ORM-модели предметной области «Складской учёт»."""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ReceiptStatus(str, enum.Enum):
    """Статус документа поступления."""

    DRAFT = "draft"  # черновик: можно редактировать
    POSTED = "posted"  # проведён: остатки увеличены, редактирование запрещено


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Unit(Base):
    """Единица измерения (шт, кг, м, л ...)."""

    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    materials: Mapped[list[Material]] = relationship(back_populates="unit")


class Supplier(Base):
    """Поставщик материалов."""

    __tablename__ = "suppliers"
    __table_args__ = (Index("ix_suppliers_name", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    inn: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    receipts: Mapped[list[Receipt]] = relationship(back_populates="supplier")


class Material(Base):
    """Материал (номенклатурная позиция) с текущим остатком на складе."""

    __tablename__ = "materials"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_materials_quantity_non_negative"),
        CheckConstraint("min_stock >= 0", name="ck_materials_min_stock_non_negative"),
        Index("ix_materials_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0")
    )
    min_stock: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0")
    )

    unit: Mapped[Unit] = relationship(back_populates="materials")
    receipt_items: Mapped[list[ReceiptItem]] = relationship(back_populates="material")


class Receipt(Base):
    """Документ поступления материалов на склад."""

    __tablename__ = "receipts"
    __table_args__ = (Index("ix_receipts_received_at", "received_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    received_at: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ReceiptStatus] = mapped_column(
        Enum(ReceiptStatus, name="receipt_status", values_callable=lambda e: [i.value for i in e]),
        nullable=False,
        default=ReceiptStatus.DRAFT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supplier: Mapped[Supplier] = relationship(back_populates="receipts")
    items: Mapped[list[ReceiptItem]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="ReceiptItem.id",
    )


class ReceiptItem(Base):
    """Строка документа поступления: материал, количество и цена."""

    __tablename__ = "receipt_items"
    __table_args__ = (
        UniqueConstraint("receipt_id", "material_id", name="uq_receipt_items_receipt_material"),
        CheckConstraint("quantity > 0", name="ck_receipt_items_quantity_positive"),
        CheckConstraint("price >= 0", name="ck_receipt_items_price_non_negative"),
        Index("ix_receipt_items_material_id", "material_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))

    receipt: Mapped[Receipt] = relationship(back_populates="items")
    material: Mapped[Material] = relationship(back_populates="receipt_items")
