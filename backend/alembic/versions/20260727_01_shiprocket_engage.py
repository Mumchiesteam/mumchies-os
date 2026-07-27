"""add Shiprocket Engage status fields

Revision ID: 20260727_01_shiprocket_engage
Revises: 20260726_01_courier_platform
"""
from alembic import op
import sqlalchemy as sa

revision = "20260727_01_shiprocket_engage"
down_revision = "20260726_01_courier_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        sa.Column("engage_order_id", sa.String(64), nullable=True),
        sa.Column("order_confirmation", sa.JSON(), nullable=True),
        sa.Column("order_confirmation_message", sa.Text(), nullable=True),
        sa.Column("address_confirmation", sa.JSON(), nullable=True),
        sa.Column("address_confirmation_message", sa.Text(), nullable=True),
        sa.Column("cod_to_prepaid", sa.JSON(), nullable=True),
        sa.Column("cod_to_prepaid_message", sa.Text(), nullable=True),
        sa.Column("engage_last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("engage_raw_status", sa.JSON(), nullable=True),
    )
    for column in columns:
        op.add_column("shiprocket_shipments", column)


def downgrade() -> None:
    for name in ("engage_raw_status", "engage_last_synced_at", "cod_to_prepaid_message", "cod_to_prepaid", "address_confirmation_message", "address_confirmation", "order_confirmation_message", "order_confirmation", "engage_order_id"):
        op.drop_column("shiprocket_shipments", name)
