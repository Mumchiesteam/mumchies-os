"""add courier issues register

Revision ID: 20260811_02_courier_issues
Revises: 20260811_01_provider_cleanup
"""

from alembic import op
import sqlalchemy as sa

revision = "20260811_02_courier_issues"
down_revision = "20260811_01_provider_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courier_issues",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("awb", sa.String(128), nullable=False),
        sa.Column("date_raised", sa.Date(), nullable=False),
        sa.Column("raised_by", sa.String(120), nullable=False),
        sa.Column("courier", sa.String(120), nullable=False),
        sa.Column("issue_type", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("closure_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("awb", "date_raised", "raised_by", "courier", "issue_type", "status"):
        op.create_index(f"ix_courier_issues_{column}", "courier_issues", [column])


def downgrade() -> None:
    op.drop_table("courier_issues")
