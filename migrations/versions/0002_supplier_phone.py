"""Контактный телефон поставщика.

Простейшее изменение схемы: новая необязательная колонка. Существующие строки
получают NULL, приложение продолжает работать без изменения данных.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("suppliers") as batch:
        batch.add_column(sa.Column("phone", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("suppliers") as batch:
        batch.drop_column("phone")
