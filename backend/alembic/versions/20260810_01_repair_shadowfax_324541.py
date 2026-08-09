"""repair stale Shadowfax client identifier for order 324541

Revision ID: 20260810_01_shadowfax_repair
Revises: 20260803_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260810_01_shadowfax_repair"
down_revision = "20260803_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    shipments = sa.table(
        "shiprocket_shipments",
        sa.column("order_id", sa.String),
        sa.column("provider", sa.String),
        sa.column("provider_order_id", sa.String),
        sa.column("shipment_id", sa.String),
        sa.column("awb", sa.String),
        sa.column("booking_status", sa.String),
        sa.column("booked_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        shipments.update()
        .where(shipments.c.order_id == "6854925713486")
        .where(sa.func.lower(shipments.c.provider) == "shadowfax")
        .where(shipments.c.provider_order_id == "324541")
        .where(shipments.c.shipment_id.is_(None))
        .where(shipments.c.awb.is_(None))
        .where(sa.func.lower(shipments.c.booking_status) == "booking_failed")
        .where(shipments.c.booked_at.is_(None))
        .values(provider_order_id=None)
    )


def downgrade() -> None:
    # Never recreate a known-false provider identifier.
    pass
