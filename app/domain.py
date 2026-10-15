"""Правила предметной области «Складской учёт» в виде чистых функций.

Модуль не знает ни о базе данных, ни о HTTP: на вход — значения, на выход —
результат или исключение RuleViolation. Поэтому правила проверяются быстрыми
unit-тестами и мутационным тестированием (`make mutation`): если изменить
любое условие ниже, тесты в tests/unit обязаны это заметить.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal

DRAFT = "draft"
POSTED = "posted"

INN_RE = re.compile(r"\d{10}|\d{12}")


class RuleViolation(Exception):
    """Запрос корректен по формату, но запрещён правилами предметной области."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details if details is not None else {}


def to_decimal(value: object) -> Decimal:
    """Число из базы, JSON или строки — в Decimal без промежуточного float."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _status_value(status: object) -> str:
    """Статус может прийти строкой или элементом перечисления ReceiptStatus."""
    return str(getattr(status, "value", status))


# ---------------------------------------------------------------------- справочники
def is_valid_inn(inn: str) -> bool:
    """ИНН юридического лица — 10 цифр, индивидуального предпринимателя — 12."""
    return INN_RE.fullmatch(inn) is not None


# ------------------------------------------------------------------------ остатки
def is_below_min(quantity: object, min_stock: object) -> bool:
    """Позиция дефицитна, если остаток строго меньше минимального запаса."""
    return to_decimal(quantity) < to_decimal(min_stock)


def ensure_positive(quantity: object) -> Decimal:
    value = to_decimal(quantity)
    if value <= 0:
        raise RuleViolation("Количество должно быть больше нуля", {"quantity": str(value)})
    return value


def apply_receipt(stock: object, quantity: object) -> Decimal:
    """Новый остаток после прихода."""
    return to_decimal(stock) + ensure_positive(quantity)


def apply_write_off(stock: object, quantity: object) -> Decimal:
    """Новый остаток после списания. Списать больше, чем есть, нельзя."""
    current = to_decimal(stock)
    requested = ensure_positive(quantity)
    if requested > current:
        raise RuleViolation(
            "Нельзя списать больше, чем есть на складе",
            {"stock": str(current), "requested": str(requested)},
        )
    return current - requested


# --------------------------------------------------------------------- поступления
def receipt_total(items: Iterable[tuple[object, object]]) -> Decimal:
    """Сумма документа: Σ количество × цена."""
    total = Decimal("0")
    for quantity, price in items:
        total += to_decimal(quantity) * to_decimal(price)
    return total


def ensure_draft(status: object, receipt_id: int | None = None) -> None:
    """Изменять можно только черновик."""
    if _status_value(status) != DRAFT:
        raise RuleViolation(
            "Проведённое поступление изменить нельзя",
            {"receipt_id": receipt_id, "status": _status_value(status)},
        )


def ensure_can_post(status: object, items_count: int, receipt_id: int | None = None) -> None:
    """Провести можно только черновик, в котором есть хотя бы одна строка."""
    ensure_draft(status, receipt_id)
    if items_count < 1:
        raise RuleViolation(
            "Нельзя провести поступление без позиций",
            {"receipt_id": receipt_id},
        )


def ensure_unique_materials(material_ids: Iterable[int]) -> None:
    """Один материал — одна строка документа."""
    seen: set[int] = set()
    for material_id in material_ids:
        if material_id in seen:
            raise RuleViolation(
                "Материал встречается в документе дважды — объедините строки",
                {"material_id": material_id},
            )
        seen.add(material_id)
