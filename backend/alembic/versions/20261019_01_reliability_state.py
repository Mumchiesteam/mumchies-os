"""add narrow durable reliability controls

Revision ID: 20261019_01_reliability_state
Revises: 20260825_02_ndr_tracking
"""
from alembic import op
import sqlalchemy as sa

revision = "20261019_01_reliability_state"
down_revision = "20260825_02_ndr_tracking"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("order_address_states", sa.Column("order_id", sa.String(32), primary_key=True), sa.Column("revision", sa.Integer(), nullable=False, server_default="0"), sa.Column("address", sa.JSON()), sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("sync_lease_revision", sa.Integer()), sa.Column("sync_lease_token", sa.String(64)), sa.Column("sync_lease_expires_at", sa.DateTime(timezone=True)), sa.Column("sync_status", sa.String(32), nullable=False, server_default="not_started"), sa.Column("sync_error", sa.Text()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("address_sync_operations", sa.Column("id", sa.String(64), primary_key=True), sa.Column("order_id", sa.String(32), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("address", sa.JSON(), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("lease_token", sa.String(64)), sa.UniqueConstraint("order_id", "revision", name="uq_address_sync_order_revision"))
    op.create_index("ix_address_sync_operations_order_id", "address_sync_operations", ["order_id"])
    op.create_table("booking_reservations", sa.Column("order_id", sa.String(32), primary_key=True), sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True), sa.Column("provider", sa.String(32), nullable=False), sa.Column("context_hash", sa.String(128), nullable=False), sa.Column("state", sa.String(32), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("provider_request_started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))

def downgrade() -> None:
    op.drop_table("booking_reservations"); op.drop_index("ix_address_sync_operations_order_id", table_name="address_sync_operations"); op.drop_table("address_sync_operations"); op.drop_table("order_address_states")
