"""remove Engage channel references from provider_order_id

Revision ID: 20260811_01_engage_provider_cleanup
Revises: 20260810_04_poller_order_no
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_01_engage_provider_cleanup"
down_revision = "20260810_04_poller_order_no"
branch_labels = None
depends_on = None


def upgrade() -> None:
    shipments = sa.table(
        "shiprocket_shipments",
        sa.column("provider", sa.String),
        sa.column("provider_order_id", sa.String),
        sa.column("shipment_id", sa.String),
        sa.column("awb", sa.String),
        sa.column("booking_status", sa.String),
        sa.column("booking_mode", sa.String),
        sa.column("booking_confidence", sa.String),
        sa.column("reconciliation_status", sa.String),
        sa.column("booked_at", sa.DateTime(timezone=True)),
    )
    # The production diagnostic established that 324663 is both the visible
    # Shopify number and the contaminated value. Other rows are repaired only
    # inside sync_engage_orders(), where the authoritative mapping is available.
    op.execute(
        shipments.update()
        .where(shipments.c.provider.is_(None))
        .where(shipments.c.provider_order_id == "324663")
        .where(shipments.c.shipment_id.is_(None))
        .where(shipments.c.awb.is_(None))
        .where(shipments.c.booking_status.is_(None))
        .where(shipments.c.booking_mode.is_(None))
        .where(shipments.c.booking_confidence.is_(None))
        .where(shipments.c.reconciliation_status.is_(None))
        .where(shipments.c.booked_at.is_(None))
        .values(provider_order_id=None)
    )


def downgrade() -> None:
    # Never recreate identifiers known to be merchant/channel references.
    pass
