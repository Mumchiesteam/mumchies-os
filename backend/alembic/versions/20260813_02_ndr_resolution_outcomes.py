"""add auditable NDR resolution outcomes

Revision ID: 20260813_02_ndr_outcomes
Revises: 20260813_01_order_read
"""
from alembic import op
import sqlalchemy as sa

revision = "20260813_02_ndr_outcomes"
down_revision = "20260813_01_order_read"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ndr_cases", sa.Column("resolution_outcome", sa.String(32), nullable=True))
    op.add_column("ndr_cases", sa.Column("resolution_source", sa.String(32), nullable=True))
    op.add_column("ndr_cases", sa.Column("resolved_by_user_id", sa.Integer(), nullable=True))
    op.add_column("ndr_cases", sa.Column("resolved_by_name", sa.String(120), nullable=True))
    op.create_foreign_key("fk_ndr_cases_resolved_by_user", "ndr_cases", "users", ["resolved_by_user_id"], ["id"])
    op.create_index("ix_ndr_cases_resolution_outcome", "ndr_cases", ["resolution_outcome"])
    op.create_index("ix_ndr_cases_resolution_source", "ndr_cases", ["resolution_source"])


def downgrade() -> None:
    op.drop_index("ix_ndr_cases_resolution_source", table_name="ndr_cases")
    op.drop_index("ix_ndr_cases_resolution_outcome", table_name="ndr_cases")
    op.drop_constraint("fk_ndr_cases_resolved_by_user", "ndr_cases", type_="foreignkey")
    op.drop_column("ndr_cases", "resolved_by_name")
    op.drop_column("ndr_cases", "resolved_by_user_id")
    op.drop_column("ndr_cases", "resolution_source")
    op.drop_column("ndr_cases", "resolution_outcome")
