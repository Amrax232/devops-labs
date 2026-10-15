"""Списания материалов.

Новая таблица для функции списания: каждая запись уменьшает остаток материала.
Количество строго положительное (CHECK), материал обязателен (FOREIGN KEY).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "write_offs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("materials.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("quantity > 0", name="ck_write_offs_quantity_positive"),
    )
    op.create_index("ix_write_offs_material_id", "write_offs", ["material_id"])


def downgrade() -> None:
    op.drop_index("ix_write_offs_material_id", table_name="write_offs")
    op.drop_table("write_offs")
