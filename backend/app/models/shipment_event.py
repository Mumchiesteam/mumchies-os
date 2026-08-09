from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class ShipmentEvent(Base):
    __tablename__ = "shipment_events"

    id = mapped_column(String(64), primary_key=True)
    order_id = mapped_column(String(32), nullable=False, index=True)
    order_number = mapped_column(String(64), nullable=True, index=True)
    shipment_reference = mapped_column(String(128), nullable=True)
    provider = mapped_column(String(32), nullable=False, index=True)
    courier_service = mapped_column(String(128), nullable=True)
    awb = mapped_column(String(128), nullable=True, index=True)
    provider_status_code = mapped_column(String(128), nullable=True)
    normalized_status = mapped_column(String(64), nullable=False, index=True)
    provider_event_at = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    recorded_at = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    location = mapped_column(Text, nullable=True)
    message = mapped_column(Text, nullable=True)
    reason = mapped_column(Text, nullable=True)
    raw_provider_event = mapped_column(Text, nullable=True)
    source = mapped_column(String(32), nullable=False, index=True)
    deduplication_key = mapped_column(String(64), nullable=False, unique=True)
