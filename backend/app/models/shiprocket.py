from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class ShiprocketShipment(Base):
    __tablename__ = "shiprocket_shipments"

    order_id = mapped_column(String(32), primary_key=True)
    shiprocket_order_id = mapped_column(String(64), nullable=True)
    shipment_id = mapped_column(String(64), nullable=True)
    awb = mapped_column(String(64), nullable=True)
    courier_name = mapped_column(String(128), nullable=True)
    courier_id = mapped_column(String(64), nullable=True)
    booking_status = mapped_column(String(64), nullable=True)
    booked_at = mapped_column(DateTime(timezone=True), nullable=True)
    latest_status = mapped_column(String(128), nullable=True)
    last_synced_at = mapped_column(DateTime(timezone=True), nullable=True)
    tracking_url = mapped_column(Text, nullable=True)
    label_url = mapped_column(Text, nullable=True)
    address_sync_status = mapped_column(String(64), nullable=True)
    address_sync_error = mapped_column(Text, nullable=True)
