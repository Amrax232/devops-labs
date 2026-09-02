"""Начальная схема: единицы измерения, поставщики, материалы, поступления.

Revision ID: 0001
Revises:
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False, unique=True),
        sa.Column("name", sa.String(length=64), nullable=False),
    )

    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False, unique=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_suppliers_name", "suppliers", ["name"])

    op.create_table(
        "materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("min_stock", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.CheckConstraint("quantity >= 0", name="ck_materials_quantity_non_negative"),
        sa.CheckConstraint("min_stock >= 0", name="ck_materials_min_stock_non_negative"),
    )
    op.create_index("ix_materials_name", "materials", ["name"])

    receipt_status = sa.Enum("draft", "posted", name="receipt_status")
    receipt_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(length=32), nullable=False, unique=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("received_at", sa.Date(), nullable=False),
        sa.Column("status", receipt_status, nullable=False, server_default="draft"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_receipts_received_at", "receipts", ["received_at"])

    op.create_table(
        "receipt_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "receipt_id",
            sa.Integer(),
            sa.ForeignKey("receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("materials.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "receipt_id", "material_id", name="uq_receipt_items_receipt_material"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_receipt_items_quantity_positive"),
        sa.CheckConstraint("price >= 0", name="ck_receipt_items_price_non_negative"),
    )
    op.create_index("ix_receipt_items_material_id", "receipt_items", ["material_id"])


def downgrade() -> None:
    op.drop_index("ix_receipt_items_material_id", table_name="receipt_items")
    op.drop_table("receipt_items")
    op.drop_index("ix_receipts_received_at", table_name="receipts")
    op.drop_table("receipts")
    sa.Enum(name="receipt_status").drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_materials_name", table_name="materials")
    op.drop_table("materials")
    op.drop_index("ix_suppliers_name", table_name="suppliers")
    op.drop_table("suppliers")
    op.drop_table("units")
