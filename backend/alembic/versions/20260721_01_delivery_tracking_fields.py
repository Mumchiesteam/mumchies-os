"""add normalized delivery tracking fields

Revision ID: 20260721_01_delivery_tracking_fields
Revises: 20260719_01_courier_provider
"""

from alembic import op
import sqlalchemy as sa

revision = "20260721_01_delivery_tracking_fields"
down_revision = "20260719_01_courier_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shiprocket_shipments", sa.Column("expected_delivery_date", sa.String(length=64), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("shiprocket_shipments", "delivered_at")
    op.drop_column("shiprocket_shipments", "expected_delivery_date")
