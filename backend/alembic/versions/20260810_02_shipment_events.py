"""add append-only canonical shipment events

Revision ID: 20260810_02_shipment_events
Revises: 20260810_01_shadowfax_repair
"""

from alembic import op
import sqlalchemy as sa


revision = "20260810_02_shipment_events"
down_revision = "20260810_01_shadowfax_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shipment_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("order_id", sa.String(32), nullable=False),
        sa.Column("order_number", sa.String(64), nullable=True),
        sa.Column("shipment_reference", sa.String(128), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("courier_service", sa.String(128), nullable=True),
        sa.Column("awb", sa.String(128), nullable=True),
        sa.Column("provider_status_code", sa.String(128), nullable=True),
        sa.Column("normalized_status", sa.String(64), nullable=False),
        sa.Column("provider_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("raw_provider_event", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("deduplication_key", sa.String(64), nullable=False, unique=True),
    )
    for column in ("order_id", "order_number", "provider", "awb", "normalized_status", "provider_event_at", "recorded_at", "source"):
        op.create_index(f"ix_shipment_events_{column}", "shipment_events", [column])


def downgrade() -> None:
    op.drop_table("shipment_events")
