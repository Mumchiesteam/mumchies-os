"""add GitHub NDR import persistence

Revision ID: 20260728_04_ndr_import
Revises: 20260728_03_ndr_parity
"""
from alembic import op
import sqlalchemy as sa

revision = "20260728_04_ndr_import"
down_revision = "20260728_03_ndr_parity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ndr_cases", sa.Column("source_identity", sa.String(320), nullable=True))
    op.add_column("ndr_cases", sa.Column("city", sa.String(160), nullable=True))
    op.add_column("ndr_cases", sa.Column("whatsapp_message", sa.Text(), nullable=True))
    op.add_column("ndr_cases", sa.Column("whatsapp_url", sa.Text(), nullable=True))
    op.execute("UPDATE ndr_cases SET source_identity = 'awb:' || awb WHERE awb IS NOT NULL AND awb <> ''")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("ndr_cases") as batch_op:
            batch_op.alter_column("awb", existing_type=sa.String(128), nullable=True)
    else:
        op.alter_column("ndr_cases", "awb", existing_type=sa.String(128), nullable=True)
    op.create_index("ix_ndr_cases_source_identity", "ndr_cases", ["source_identity"], unique=True)
    op.create_table(
        "ndr_import_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(160), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_health", sa.JSON(), nullable=False),
        sa.Column("source_counts", sa.JSON(), nullable=False),
        sa.Column("rows_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("safe_errors", sa.JSON(), nullable=True),
    )
    op.create_index("ix_ndr_import_runs_run_id", "ndr_import_runs", ["run_id"], unique=True)
    op.create_index("ix_ndr_import_runs_status", "ndr_import_runs", ["status"])


def downgrade() -> None:
    op.drop_table("ndr_import_runs")
    op.drop_index("ix_ndr_cases_source_identity", table_name="ndr_cases")
    op.drop_column("ndr_cases", "whatsapp_url")
    op.drop_column("ndr_cases", "whatsapp_message")
    op.drop_column("ndr_cases", "city")
    op.drop_column("ndr_cases", "source_identity")
