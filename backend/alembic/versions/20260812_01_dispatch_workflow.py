"""add internal dispatch workflow state

Revision ID: 20260812_01_dispatch
Revises: 20260811_02_courier_issues
"""
from alembic import op
import sqlalchemy as sa

revision = "20260812_01_dispatch"
down_revision = "20260811_02_courier_issues"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("shiprocket_shipments", sa.Column("dispatch_status", sa.String(32), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("manifested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("manifested_by", sa.String(128), nullable=True))
    op.execute("UPDATE shiprocket_shipments SET dispatch_status = 'ready_to_ship' WHERE booking_status = 'booked' AND awb IS NOT NULL AND awb <> ''")
    op.create_index("ix_shiprocket_shipments_dispatch_status", "shiprocket_shipments", ["dispatch_status"])

def downgrade() -> None:
    op.drop_index("ix_shiprocket_shipments_dispatch_status", table_name="shiprocket_shipments")
    op.drop_column("shiprocket_shipments", "manifested_by")
    op.drop_column("shiprocket_shipments", "manifested_at")
    op.drop_column("shiprocket_shipments", "dispatch_status")
