"""clear untrusted poller audit order numbers

Revision ID: 20260810_04_poller_order_no
Revises: 20260810_03_poller_audit
"""

from alembic import op
import sqlalchemy as sa


revision = "20260810_04_poller_order_no"
down_revision = "20260810_03_poller_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All values written before this revision came from provider_order_id and are
    # not trustworthy Shopify order numbers. Preserve the attempts, but clear the
    # misleading display value.
    op.execute(sa.text("UPDATE shipment_poll_attempts SET order_number = NULL WHERE order_number IS NOT NULL"))


def downgrade() -> None:
    # The discarded values were semantically invalid and must not be reconstructed.
    pass
