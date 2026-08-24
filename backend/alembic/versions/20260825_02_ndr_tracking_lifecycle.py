"""add durable NDR tracking lifecycle

Revision ID: 20260825_02_ndr_tracking
Revises: 20260825_01_gst_snapshots
"""
from alembic import op
import sqlalchemy as sa

revision = "20260825_02_ndr_tracking"
down_revision = "20260825_01_gst_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ndr_cases", sa.Column("tracking_enrolled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ndr_cases", sa.Column("tracking_next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ndr_cases", sa.Column("tracking_last_attempted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ndr_cases", sa.Column("tracking_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ndr_cases", sa.Column("tracking_attempt_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("ndr_cases", sa.Column("tracking_consecutive_failures", sa.Integer(), server_default="0", nullable=False))
    op.add_column("ndr_cases", sa.Column("tracking_last_result", sa.String(length=32), nullable=True))
    op.add_column("ndr_cases", sa.Column("tracking_classification", sa.String(length=32), nullable=True))
    op.add_column("ndr_cases", sa.Column("tracking_classified_at", sa.DateTime(timezone=True), nullable=True))
    for name, column in (("ix_ndr_cases_tracking_enrolled_at", "tracking_enrolled_at"), ("ix_ndr_cases_tracking_next_attempt_at", "tracking_next_attempt_at"), ("ix_ndr_cases_tracking_expires_at", "tracking_expires_at"), ("ix_ndr_cases_tracking_classification", "tracking_classification")):
        op.create_index(name, "ndr_cases", [column])


def downgrade() -> None:
    for name in ("ix_ndr_cases_tracking_classification", "ix_ndr_cases_tracking_expires_at", "ix_ndr_cases_tracking_next_attempt_at", "ix_ndr_cases_tracking_enrolled_at"):
        op.drop_index(name, table_name="ndr_cases")
    for column in ("tracking_classified_at", "tracking_classification", "tracking_last_result", "tracking_consecutive_failures", "tracking_attempt_count", "tracking_expires_at", "tracking_last_attempted_at", "tracking_next_attempt_at", "tracking_enrolled_at"):
        op.drop_column("ndr_cases", column)
