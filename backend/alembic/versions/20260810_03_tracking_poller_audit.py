"""add bounded shipment tracking poller audit

Revision ID: 20260810_03_poller_audit
Revises: 20260810_02_shipment_events
"""

from alembic import op
import sqlalchemy as sa


revision = "20260810_03_poller_audit"
down_revision = "20260810_02_shipment_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shipment_poll_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_attempted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_events_persisted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_counts", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
    )
    op.create_table(
        "shipment_poll_attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("shipment_poll_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.String(32), nullable=False),
        sa.Column("order_number", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("courier_service", sa.String(128), nullable=True),
        sa.Column("awb_reference", sa.String(128), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("error_category", sa.String(64), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("events_returned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_events_persisted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("terminal_status_detected", sa.String(64), nullable=True),
        sa.Column("response_format", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
    )
    for table, columns in {
        "shipment_poll_runs": ("started_at", "completed_at", "status"),
        "shipment_poll_attempts": ("run_id", "order_id", "order_number", "provider", "awb_reference", "attempted_at", "result", "error_category"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("shipment_poll_attempts")
    op.drop_table("shipment_poll_runs")
