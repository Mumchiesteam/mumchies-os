"""add generic courier provider identifiers

Revision ID: 20260719_01_courier_provider
Revises: 20260718_01_shiprocket_package_details
"""

from alembic import op
import sqlalchemy as sa

revision = "20260719_01_courier_provider"
down_revision = "20260718_01_shiprocket_package_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shiprocket_shipments", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("provider_order_id", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("shiprocket_shipments", "provider_order_id")
    op.drop_column("shiprocket_shipments", "provider")
