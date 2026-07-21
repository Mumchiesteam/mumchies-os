"""add shiprocket package details and selected courier

Revision ID: 20260718_01_shiprocket_package_details
Revises: 20260717_01_shiprocket_shipments
Create Date: 2026-07-18 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260718_01_shiprocket_package_details"
down_revision = "20260717_01_shiprocket_shipments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shiprocket_shipments", sa.Column("package_weight_kg", sa.Float(), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("package_length_cm", sa.Float(), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("package_breadth_cm", sa.Float(), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("package_height_cm", sa.Float(), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("selected_courier_id", sa.String(length=64), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("selected_courier_name", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("shiprocket_shipments", "selected_courier_name")
    op.drop_column("shiprocket_shipments", "selected_courier_id")
    op.drop_column("shiprocket_shipments", "package_height_cm")
    op.drop_column("shiprocket_shipments", "package_breadth_cm")
    op.drop_column("shiprocket_shipments", "package_length_cm")
    op.drop_column("shiprocket_shipments", "package_weight_kg")
