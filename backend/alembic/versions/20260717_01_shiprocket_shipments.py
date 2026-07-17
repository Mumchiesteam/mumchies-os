"""create shiprocket shipments table

Revision ID: 20260717_01_shiprocket_shipments
Revises: 
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260717_01_shiprocket_shipments"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shiprocket_shipments",
        sa.Column("order_id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("shiprocket_order_id", sa.String(length=64), nullable=True),
        sa.Column("shipment_id", sa.String(length=64), nullable=True),
        sa.Column("awb", sa.String(length=64), nullable=True),
        sa.Column("courier_name", sa.String(length=128), nullable=True),
        sa.Column("courier_id", sa.String(length=64), nullable=True),
        sa.Column("booking_status", sa.String(length=64), nullable=True),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_status", sa.String(length=128), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracking_url", sa.Text(), nullable=True),
        sa.Column("label_url", sa.Text(), nullable=True),
        sa.Column("address_sync_status", sa.String(length=64), nullable=True),
        sa.Column("address_sync_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("shiprocket_shipments")
