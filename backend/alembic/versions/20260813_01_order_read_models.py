"""add cached canonical order read models

Revision ID: 20260813_01_order_read
Revises: 20260812_01_dispatch
"""
from alembic import op
import sqlalchemy as sa
revision = "20260813_01_order_read"
down_revision = "20260812_01_dispatch"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("order_read_models", sa.Column("order_id", sa.String(32), primary_key=True), sa.Column("order_number", sa.String(64), nullable=False), sa.Column("customer_name", sa.String(300)), sa.Column("payment_type", sa.String(32)), sa.Column("order_value", sa.Float()), sa.Column("products", sa.JSON()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_order_read_models_order_number", "order_read_models", ["order_number"], unique=True)

def downgrade() -> None:
    op.drop_index("ix_order_read_models_order_number", table_name="order_read_models")
    op.drop_table("order_read_models")
