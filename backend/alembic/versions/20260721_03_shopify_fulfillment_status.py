"""add Shopify fulfillment status

Revision ID: 20260721_03_shopify_fulfillment_status
Revises: 20260721_02_shopify_fulfillment_sync
"""

from alembic import op
import sqlalchemy as sa

revision = "20260721_03_shopify_fulfillment_status"
down_revision = "20260721_02_shopify_fulfillment_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shiprocket_shipments", sa.Column("shopify_fulfillment_status", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("shiprocket_shipments", "shopify_fulfillment_status")
