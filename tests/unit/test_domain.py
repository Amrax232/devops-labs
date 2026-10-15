"""Unit-тесты правил предметной области (app/domain.py).

Тесты не используют ни базу данных, ни HTTP и проверяют каждое условие на
границе: значение «ровно на пороге», «чуть ниже» и «чуть выше». Именно такие
тесты ловят подмену `<` на `<=`, которую делает мутационное тестирование
(make mutation) и которую на защите вносит преподаватель.
"""

import enum
from decimal import Decimal

import pytest

from app import domain
from app.domain import RuleViolation


# --------------------------------------------------------------------- RuleViolation
def test_rule_violation_keeps_message_and_details() -> None:
    error = RuleViolation("Сообщение", {"id": 7})

    assert str(error) == "Сообщение"
    assert error.message == "Сообщение"
    assert error.details == {"id": 7}


def test_rule_violation_details_default_to_empty_dict() -> None:
    assert RuleViolation("Сообщение").details == {}


# ------------------------------------------------------------------------ to_decimal
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (Decimal("1.5"), Decimal("1.5")),
        ("2.25", Decimal("2.25")),
        (3, Decimal("3")),
        # float переводится через строку: 0.1 остаётся 0.1, а не 0.1000000000000000055…
        (0.1, Decimal("0.1")),
    ],
)
def test_to_decimal(raw: object, expected: Decimal) -> None:
    assert domain.to_decimal(raw) == expected
    assert isinstance(domain.to_decimal(raw), Decimal)


# ------------------------------------------------------------------------------ ИНН
@pytest.mark.parametrize(
    ("inn", "valid"),
    [
        ("770123456", False),  # 9 цифр
        ("7701234567", True),  # 10 цифр — юридическое лицо
        ("77012345678", False),  # 11 цифр
        ("540112233445", True),  # 12 цифр — индивидуальный предприниматель
        ("5401122334455", False),  # 13 цифр
        ("77012345a7", False),  # буква
        (" 7701234567", False),  # пробел
        ("", False),
    ],
)
def test_inn_validation(inn: str, valid: bool) -> None:
    assert domain.is_valid_inn(inn) is valid


# ------------------------------------------------------------- минимальный запас
@pytest.mark.parametrize(
    ("quantity", "min_stock", "expected"),
    [
        ("49.999", "50", True),  # чуть ниже минимума — дефицит
        ("50", "50", False),  # ровно минимум — ещё не дефицит
        ("50.001", "50", False),  # чуть выше
        ("0", "0", False),  # минимум не задан
    ],
)
def test_is_below_min(quantity: str, min_stock: str, expected: bool) -> None:
    assert domain.is_below_min(quantity, min_stock) is expected


# --------------------------------------------------------------------- количество
@pytest.mark.parametrize("quantity", ["0", "-0.001", "-5"])
def test_non_positive_quantity_is_rejected(quantity: str) -> None:
    with pytest.raises(RuleViolation) as error:
        domain.ensure_positive(quantity)
    assert error.value.details == {"quantity": str(Decimal(quantity))}


@pytest.mark.parametrize("quantity", ["0.001", "0.5", "1", "2"])
def test_positive_quantity_is_accepted(quantity: str) -> None:
    assert domain.ensure_positive(quantity) == Decimal(quantity)


# ------------------------------------------------------------------------- приход
def test_receipt_increases_stock() -> None:
    assert domain.apply_receipt("10", "2.5") == Decimal("12.5")


def test_receipt_into_empty_stock() -> None:
    assert domain.apply_receipt(Decimal("0"), "0.001") == Decimal("0.001")


def test_receipt_with_zero_quantity_is_rejected() -> None:
    with pytest.raises(RuleViolation):
        domain.apply_receipt("10", "0")


# ------------------------------------------------------------------------ списание
def test_write_off_decreases_stock() -> None:
    assert domain.apply_write_off("10", "3") == Decimal("7")


def test_write_off_of_whole_stock_is_allowed() -> None:
    assert domain.apply_write_off("10", "10") == Decimal("0")


def test_write_off_over_stock_is_rejected() -> None:
    with pytest.raises(RuleViolation) as error:
        domain.apply_write_off("10", "10.001")

    assert error.value.message == "Нельзя списать больше, чем есть на складе"
    assert error.value.details == {"stock": "10", "requested": "10.001"}


def test_write_off_from_empty_stock_is_rejected() -> None:
    with pytest.raises(RuleViolation):
        domain.apply_write_off("0", "1")


def test_write_off_with_zero_quantity_is_rejected() -> None:
    with pytest.raises(RuleViolation):
        domain.apply_write_off("10", "0")


# ---------------------------------------------------------------- сумма документа
def test_receipt_total() -> None:
    items = [("10.5", "25.50"), ("2", "100")]
    assert domain.receipt_total(items) == Decimal("10.5") * Decimal("25.50") + Decimal("200")


def test_receipt_total_of_empty_document_is_zero() -> None:
    assert domain.receipt_total([]) == Decimal("0")


# --------------------------------------------------------- статус и проведение
def test_draft_can_be_edited() -> None:
    domain.ensure_draft("draft", 1)


def test_posted_receipt_cannot_be_edited() -> None:
    with pytest.raises(RuleViolation) as error:
        domain.ensure_draft("posted", 5)

    assert error.value.details == {"receipt_id": 5, "status": "posted"}


class _Status(str, enum.Enum):
    """Такое же перечисление, как ReceiptStatus в моделях, но без импорта БД."""

    DRAFT = "draft"
    POSTED = "posted"


def test_status_may_be_enum_member() -> None:
    domain.ensure_draft(_Status.DRAFT, 1)
    with pytest.raises(RuleViolation) as error:
        domain.ensure_draft(_Status.POSTED, 1)
    assert error.value.details["status"] == "posted"


@pytest.mark.parametrize("items_count", [1, 2, 10])
def test_draft_with_items_can_be_posted(items_count: int) -> None:
    domain.ensure_can_post("draft", items_count, 1)


def test_empty_draft_cannot_be_posted() -> None:
    with pytest.raises(RuleViolation) as error:
        domain.ensure_can_post("draft", 0, 3)

    assert error.value.message == "Нельзя провести поступление без позиций"
    assert error.value.details == {"receipt_id": 3}


def test_posted_receipt_cannot_be_posted_again() -> None:
    with pytest.raises(RuleViolation) as error:
        domain.ensure_can_post("posted", 2, 4)

    assert error.value.message == "Проведённое поступление изменить нельзя"


# --------------------------------------------------------- уникальность строк
@pytest.mark.parametrize("material_ids", [[], [1], [1, 2, 3]])
def test_unique_materials_are_accepted(material_ids: list[int]) -> None:
    domain.ensure_unique_materials(material_ids)


@pytest.mark.parametrize(("material_ids", "duplicate"), [([1, 1], 1), ([1, 2, 3, 2], 2)])
def test_duplicate_material_is_rejected(material_ids: list[int], duplicate: int) -> None:
    with pytest.raises(RuleViolation) as error:
        domain.ensure_unique_materials(material_ids)

    assert error.value.details == {"material_id": duplicate}
