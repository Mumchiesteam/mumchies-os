"""add Shopify fulfillment synchronization fields

Revision ID: 20260721_02_shopify_fulfillment_sync
Revises: 20260721_01_delivery_tracking_fields
"""

from alembic import op
import sqlalchemy as sa

revision = "20260721_02_shopify_fulfillment_sync"
down_revision = "20260721_01_delivery_tracking_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shiprocket_shipments", sa.Column("shopify_fulfillment_id", sa.String(length=128), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("shopify_fulfillment_sync_status", sa.String(length=32), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("shopify_fulfillment_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("shopify_fulfillment_sync_error", sa.Text(), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("shopify_tracking_number", sa.String(length=128), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("shopify_tracking_url", sa.Text(), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("shopify_customer_notified", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("shiprocket_shipments", "shopify_customer_notified")
    op.drop_column("shiprocket_shipments", "shopify_tracking_url")
    op.drop_column("shiprocket_shipments", "shopify_tracking_number")
    op.drop_column("shiprocket_shipments", "shopify_fulfillment_sync_error")
    op.drop_column("shiprocket_shipments", "shopify_fulfillment_synced_at")
    op.drop_column("shiprocket_shipments", "shopify_fulfillment_sync_status")
    op.drop_column("shiprocket_shipments", "shopify_fulfillment_id")
