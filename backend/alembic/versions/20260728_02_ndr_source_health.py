"""add per-source NDR sync health

Revision ID: 20260728_02_ndr_source_health
Revises: 20260728_01_ndr_module
"""
from alembic import op
import sqlalchemy as sa

revision = "20260728_02_ndr_source_health"
down_revision = "20260728_01_ndr_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ndr_sync_runs", sa.Column("source_health", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("ndr_sync_runs", "source_health")
