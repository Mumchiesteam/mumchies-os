"""add immutable GST report snapshots

Revision ID: 20260825_01_gst_snapshots
Revises: 20260813_02_ndr_outcomes
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260825_01_gst_snapshots"
down_revision = "20260813_02_ndr_outcomes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gst_report_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("finalised_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("methodology_version", sa.String(64), nullable=False),
        sa.Column("delivered_order_count", sa.Integer(), nullable=False),
        sa.Column("taxable_value", sa.Numeric(16, 2), nullable=False),
        sa.Column("cgst", sa.Numeric(16, 2), nullable=False),
        sa.Column("sgst", sa.Numeric(16, 2), nullable=False),
        sa.Column("igst", sa.Numeric(16, 2), nullable=False),
        sa.Column("total_gst", sa.Numeric(16, 2), nullable=False),
        sa.Column("gross_sales", sa.Numeric(16, 2), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("csv_content", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checksum"),
        sa.UniqueConstraint("month"),
    )
    op.create_index("ix_gst_report_snapshots_month", "gst_report_snapshots", ["month"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_gst_report_snapshots_month", table_name="gst_report_snapshots")
    op.drop_table("gst_report_snapshots")
