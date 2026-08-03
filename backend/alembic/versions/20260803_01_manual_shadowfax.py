"""add manual Shadowfax booking fields

Revision ID: 20260803_01
Revises: 20260728_04_ndr_import
"""
from alembic import op
import sqlalchemy as sa

revision = "20260803_01"
down_revision = "20260728_04_ndr_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shiprocket_shipments", sa.Column("booking_mode", sa.String(32), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("booking_freight", sa.Float(), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("booking_operator", sa.String(128), nullable=True))
    op.add_column("shiprocket_shipments", sa.Column("booking_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("shiprocket_shipments", "booking_note")
    op.drop_column("shiprocket_shipments", "booking_operator")
    op.drop_column("shiprocket_shipments", "booking_freight")
    op.drop_column("shiprocket_shipments", "booking_mode")
