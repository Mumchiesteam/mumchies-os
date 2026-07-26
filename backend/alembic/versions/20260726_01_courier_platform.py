"""add provider-neutral courier platform fields

Revision ID: 20260726_01_courier_platform
Revises: 20260721_04_label_printing
"""

from alembic import op
import sqlalchemy as sa

revision = "20260726_01_courier_platform"
down_revision = "20260721_04_label_printing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        sa.Column("normalized_status", sa.String(64), nullable=True),
        sa.Column("courier_service", sa.String(128), nullable=True),
        sa.Column("latest_tracking_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_scan", sa.Text(), nullable=True),
        sa.Column("terminal_status", sa.String(64), nullable=True),
        sa.Column("label_format", sa.String(16), nullable=True),
        sa.Column("raw_provider_response", sa.Text(), nullable=True),
        sa.Column("booking_confidence", sa.String(32), nullable=True),
        sa.Column("reconciliation_status", sa.String(32), nullable=True),
        sa.Column("reconciliation_error", sa.Text(), nullable=True),
        sa.Column("ndr_reason", sa.Text(), nullable=True),
        sa.Column("ndr_attempt", sa.Integer(), nullable=True),
        sa.Column("ndr_remarks", sa.Text(), nullable=True),
        sa.Column("ndr_operator_action", sa.Text(), nullable=True),
    )
    for column in columns:
        op.add_column("shiprocket_shipments", column)
    op.create_index("ix_shipments_provider_order", "shiprocket_shipments", ["provider", "provider_order_id"], unique=False)
    op.create_index("ix_shipments_reconciliation", "shiprocket_shipments", ["provider", "reconciliation_status"], unique=False)
    op.create_table(
        "courier_webhook_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(128), nullable=False),
        sa.Column("order_id", sa.String(32), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_courier_webhook_provider_event"),
    )


def downgrade() -> None:
    op.drop_table("courier_webhook_events")
    op.drop_index("ix_shipments_reconciliation", table_name="shiprocket_shipments")
    op.drop_index("ix_shipments_provider_order", table_name="shiprocket_shipments")
    for name in ("ndr_operator_action", "ndr_remarks", "ndr_attempt", "ndr_reason", "reconciliation_error", "reconciliation_status", "booking_confidence", "raw_provider_response", "label_format", "terminal_status", "latest_scan", "latest_tracking_at", "courier_service", "normalized_status"):
        op.drop_column("shiprocket_shipments", name)
