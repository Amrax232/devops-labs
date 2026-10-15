"""Место хранения материала.

Колонка обязательная (NOT NULL). Добавить такую колонку в таблицу, где уже есть
строки, можно только со значением по умолчанию: иначе база не сможет заполнить
её у существующих записей и миграция упадёт. Поэтому server_default='MAIN' —
все ранее заведённые материалы окажутся на основном складе.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("materials") as batch:
        batch.add_column(
            sa.Column(
                "location",
                sa.String(length=32),
                nullable=False,
                server_default="MAIN",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("materials") as batch:
        batch.drop_column("location")
