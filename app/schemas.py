"""Схемы запросов и ответов (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.models import ReceiptStatus

INN_RE = re.compile(r"^\d{10}$|^\d{12}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


# ---------------------------------------------------------------- единицы измерения
class UnitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=16, examples=["kg"])
    name: str = Field(min_length=1, max_length=64, examples=["Килограмм"])


class UnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


# ------------------------------------------------------------------------ поставщики
class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, examples=['ООО "Метизы"'])
    inn: str = Field(examples=["7701234567"])
    email: str | None = Field(default=None, examples=["sales@metiz.example"])
    is_active: bool = True

    @field_validator("inn")
    @classmethod
    def validate_inn(cls, value: str) -> str:
        if not INN_RE.match(value):
            raise ValueError("ИНН должен содержать 10 или 12 цифр")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and not EMAIL_RE.match(value):
            raise ValueError("Некорректный адрес электронной почты")
        return value


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and not EMAIL_RE.match(value):
            raise ValueError("Некорректный адрес электронной почты")
        return value


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    inn: str
    email: str | None
    is_active: bool


# -------------------------------------------------------------------------- материалы
class MaterialCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=32, examples=["MAT-001"])
    name: str = Field(min_length=1, max_length=255, examples=["Болт М8х40"])
    unit_id: int
    min_stock: Decimal = Field(default=Decimal("0"), ge=0)


class MaterialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    unit_id: int | None = None
    min_stock: Decimal | None = Field(default=None, ge=0)


class MaterialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    quantity: Decimal
    min_stock: Decimal
    unit: UnitRead


# ------------------------------------------------------------------------ поступления
class ReceiptItemCreate(BaseModel):
    material_id: int
    quantity: Decimal = Field(gt=0, examples=["10.000"])
    price: Decimal = Field(default=Decimal("0"), ge=0, examples=["25.50"])


class ReceiptItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_id: int
    quantity: Decimal
    price: Decimal


class ReceiptCreate(BaseModel):
    number: str = Field(min_length=1, max_length=32, examples=["ПН-0001"])
    supplier_id: int
    received_at: date
    items: list[ReceiptItemCreate] = Field(default_factory=list)


class ReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    supplier_id: int
    received_at: date
    status: ReceiptStatus
    created_at: datetime | None = None
    posted_at: datetime | None = None
    items: list[ReceiptItemRead] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_amount(self) -> Decimal:
        return sum((i.quantity * i.price for i in self.items), Decimal("0"))


# ----------------------------------------------------------------------------- отчёты
class StockRow(BaseModel):
    material_id: int
    sku: str
    name: str
    unit_code: str
    quantity: Decimal
    min_stock: Decimal
    below_min: bool


class StockReport(BaseModel):
    rows: list[StockRow]
    positions: int


class SupplierSummaryRow(BaseModel):
    supplier_id: int
    supplier_name: str
    receipts_count: int
    total_amount: Decimal


class ReceiptsReport(BaseModel):
    date_from: date | None
    date_to: date | None
    rows: list[SupplierSummaryRow]
    total_amount: Decimal


# ------------------------------------------------------------------------ служебное
class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
