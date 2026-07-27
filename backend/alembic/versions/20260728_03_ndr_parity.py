"""add NDR source lifecycle

Revision ID: 20260728_03_ndr_parity
Revises: 20260728_02_ndr_source_health
"""
from alembic import op
import sqlalchemy as sa

revision = "20260728_03_ndr_parity"
down_revision = "20260728_02_ndr_source_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ndr_cases", sa.Column("source_lifecycle", sa.String(32), nullable=False, server_default="active"))
    op.create_index("ix_ndr_cases_source_lifecycle", "ndr_cases", ["source_lifecycle"])


def downgrade() -> None:
    op.drop_index("ix_ndr_cases_source_lifecycle", table_name="ndr_cases")
    op.drop_column("ndr_cases", "source_lifecycle")
