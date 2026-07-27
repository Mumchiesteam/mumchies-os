"""add complete NDR module

Revision ID: 20260728_01_ndr_module
Revises: 20260727_02_users
"""
from alembic import op
import sqlalchemy as sa

revision = "20260728_01_ndr_module"
down_revision = "20260727_02_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("ndr_sync_runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("source", sa.String(32), nullable=False), sa.Column("trigger", sa.String(32), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("lock_key", sa.String(32), unique=True), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("cases_seen", sa.Integer(), nullable=False, server_default="0"), sa.Column("cases_created", sa.Integer(), nullable=False, server_default="0"), sa.Column("cases_updated", sa.Integer(), nullable=False, server_default="0"), sa.Column("error", sa.Text()), sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("actor_name", sa.String(120)))
    op.create_index("ix_ndr_sync_runs_status", "ndr_sync_runs", ["status"])
    op.create_table("ndr_cases", sa.Column("id", sa.String(36), primary_key=True), sa.Column("awb", sa.String(128), nullable=False, unique=True), sa.Column("order_id", sa.String(64)), sa.Column("order_number", sa.String(64)), sa.Column("provider", sa.String(32), nullable=False), sa.Column("courier_name", sa.String(128)), sa.Column("customer_name", sa.String(160)), sa.Column("customer_phone", sa.String(32)), sa.Column("customer_address", sa.JSON()), sa.Column("products", sa.JSON()), sa.Column("cod_amount", sa.Float(), nullable=False, server_default="0"), sa.Column("shopify_order_url", sa.Text()), sa.Column("provider_tracking_url", sa.Text()), sa.Column("current_status", sa.String(64), nullable=False), sa.Column("provider_status", sa.String(128)), sa.Column("failure_reason", sa.Text()), sa.Column("recommended_action", sa.Text()), sa.Column("priority", sa.String(16), nullable=False), sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="1"), sa.Column("assigned_to_user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("assigned_to_name", sa.String(120)), sa.Column("first_ndr_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_provider_update_at", sa.DateTime(timezone=True)), sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False), sa.Column("customer_contacted_at", sa.DateTime(timezone=True)), sa.Column("courier_contacted_at", sa.DateTime(timezone=True)), sa.Column("resolved_at", sa.DateTime(timezone=True)), sa.Column("resolution_note", sa.Text()), sa.Column("raw_provider_data", sa.JSON()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for column in ("awb", "order_id", "order_number", "provider", "current_status", "failure_reason", "priority", "assigned_to_user_id"): op.create_index(f"ix_ndr_cases_{column}", "ndr_cases", [column])
    op.create_table("ndr_events", sa.Column("id", sa.String(36), primary_key=True), sa.Column("case_id", sa.String(36), sa.ForeignKey("ndr_cases.id", ondelete="CASCADE"), nullable=False), sa.Column("event_type", sa.String(64), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("actor_name", sa.String(120)), sa.Column("event_data", sa.JSON()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for column in ("case_id", "event_type", "created_at"): op.create_index(f"ix_ndr_events_{column}", "ndr_events", [column])


def downgrade() -> None:
    op.drop_table("ndr_events")
    op.drop_table("ndr_cases")
    op.drop_table("ndr_sync_runs")
