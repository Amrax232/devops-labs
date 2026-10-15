"""Миграции схемы базы данных на настоящем PostgreSQL.

Проверяется то, что требуется от миграций в работе:
- чистая база создаётся с нуля до последней версии;
- база, в которой уже есть данные, обновляется без их потери;
- каждая миграция обратима;
- модели в коде совпадают со схемой, которую строят миграции.
"""

from decimal import Decimal

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from app import models  # noqa: F401 - импорт регистрирует модели в Base.metadata
from app.db import Base

EXPECTED_TABLES = {
    "units",
    "suppliers",
    "materials",
    "receipts",
    "receipt_items",
    "write_offs",
    "alembic_version",
}


def _current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_migration_history_is_linear(alembic_cfg: Config) -> None:
    script = ScriptDirectory.from_config(alembic_cfg)
    revisions = list(script.walk_revisions("base", "heads"))

    assert len(script.get_heads()) == 1, "у истории миграций несколько вершин"
    assert len(revisions) >= 4  # начальная схема + три последовательных изменения


def test_clean_database_is_created_from_scratch(engine: Engine, alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")

    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    assert _current_revision(engine) == ScriptDirectory.from_config(alembic_cfg).get_current_head()


def test_database_with_data_is_upgraded_without_loss(
    engine: Engine, alembic_cfg: Config
) -> None:
    # 1. Схема в состоянии «до» — версия 0002, где ещё нет места хранения и списаний.
    command.upgrade(alembic_cfg, "0002")
    with engine.begin() as connection:
        unit_id = connection.execute(
            text("INSERT INTO units (code, name) VALUES ('pcs', 'Штука') RETURNING id")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO materials (sku, name, unit_id, quantity, min_stock) "
                "VALUES ('MAT-001', 'Болт М8х40', :unit_id, 125.5, 10)"
            ),
            {"unit_id": unit_id},
        )
        connection.execute(
            text(
                "INSERT INTO suppliers (name, inn, is_active, phone) "
                "VALUES ('ООО Метизы', '7701234567', true, '+7 495 000-00-00')"
            )
        )

    # 2. Обновление до последней версии.
    command.upgrade(alembic_cfg, "head")

    # 3. Данные на месте, новая обязательная колонка заполнена значением по умолчанию.
    with engine.connect() as connection:
        material = connection.execute(text("SELECT sku, quantity, location FROM materials")).one()
        supplier = connection.execute(text("SELECT inn, phone FROM suppliers")).one()
        write_offs = connection.execute(text("SELECT count(*) FROM write_offs")).scalar_one()

    assert material.sku == "MAT-001"
    assert material.quantity == Decimal("125.500")
    assert material.location == "MAIN"
    assert supplier.phone == "+7 495 000-00-00"
    assert write_offs == 0


def test_downgrade_to_base_removes_everything(engine: Engine, alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")

    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    with engine.connect() as connection:
        enum_left = connection.execute(
            text("SELECT count(*) FROM pg_type WHERE typname = 'receipt_status'")
        ).scalar_one()
    assert enum_left == 0

    command.upgrade(alembic_cfg, "head")
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_every_migration_is_reversible(engine: Engine, alembic_cfg: Config) -> None:
    """«Лестница»: каждый шаг — вверх, вниз и снова вверх."""
    script = ScriptDirectory.from_config(alembic_cfg)
    for revision in reversed(list(script.walk_revisions("base", "heads"))):
        command.upgrade(alembic_cfg, revision.revision)
        command.downgrade(alembic_cfg, revision.down_revision or "base")
        command.upgrade(alembic_cfg, revision.revision)

    assert _current_revision(engine) == script.get_current_head()


def test_models_match_migrations(engine: Engine, alembic_cfg: Config) -> None:
    """Если поменяли модель и забыли миграцию — этот тест упадёт."""
    command.upgrade(alembic_cfg, "head")

    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert diff == [], f"модели расходятся со схемой, нужна миграция: {diff}"
