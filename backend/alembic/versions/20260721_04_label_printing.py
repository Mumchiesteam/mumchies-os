"""add label printing and address confidence state

Revision ID: 20260721_04_label_printing
Revises: 20260721_03_shopify_fulfillment_status
"""

from alembic import op
import sqlalchemy as sa

revision = "20260721_04_label_printing"
down_revision = "20260721_03_shopify_fulfillment_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("label_print_status", sa.String(32), nullable=True),
        sa.Column("label_first_printed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("label_last_printed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("label_last_printed_by", sa.String(128), nullable=True),
        sa.Column("label_print_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_print_batch_id", sa.String(64), nullable=True),
        sa.Column("label_tracking_activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("address_confidence_score", sa.Float(), nullable=True),
        sa.Column("address_confidence_category", sa.String(64), nullable=True),
        sa.Column("address_confidence_source", sa.String(64), nullable=True),
        sa.Column("address_confidence_checked_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("shiprocket_shipments", column)
    op.create_table(
        "label_print_batches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(128), nullable=True),
        sa.Column("pdf_cache_path", sa.Text(), nullable=True),
    )
    op.create_table(
        "label_print_batch_items",
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("order_id", sa.String(32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("batch_id", "order_id"),
        sa.ForeignKeyConstraint(["batch_id"], ["label_print_batches.id"]),
    )


def downgrade() -> None:
    op.drop_table("label_print_batch_items")
    op.drop_table("label_print_batches")
    for name in ("address_confidence_checked_at", "address_confidence_source", "address_confidence_category", "address_confidence_score", "label_tracking_activated_at", "last_print_batch_id", "label_print_count", "label_last_printed_by", "label_last_printed_at", "label_first_printed_at", "label_print_status"):
        op.drop_column("shiprocket_shipments", name)
