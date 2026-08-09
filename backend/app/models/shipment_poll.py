from __future__ import annotations

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class ShipmentPollRun(Base):
    __tablename__ = "shipment_poll_runs"

    run_id = mapped_column(String(64), primary_key=True)
    started_at = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    total_attempted = mapped_column(Integer, nullable=False, default=0)
    total_succeeded = mapped_column(Integer, nullable=False, default=0)
    total_failed = mapped_column(Integer, nullable=False, default=0)
    new_events_persisted = mapped_column(Integer, nullable=False, default=0)
    provider_counts = mapped_column(JSON, nullable=False, default=dict)
    status = mapped_column(String(32), nullable=False, index=True)


class ShipmentPollAttempt(Base):
    __tablename__ = "shipment_poll_attempts"

    id = mapped_column(String(64), primary_key=True)
    run_id = mapped_column(String(64), ForeignKey("shipment_poll_runs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = mapped_column(String(32), nullable=False, index=True)
    order_number = mapped_column(String(64), nullable=True, index=True)
    provider = mapped_column(String(32), nullable=False, index=True)
    courier_service = mapped_column(String(128), nullable=True)
    awb_reference = mapped_column(String(128), nullable=True, index=True)
    attempted_at = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    result = mapped_column(String(32), nullable=False, index=True)
    error_category = mapped_column(String(64), nullable=True, index=True)
    http_status = mapped_column(Integer, nullable=True)
    error_summary = mapped_column(Text, nullable=True)
    events_returned = mapped_column(Integer, nullable=False, default=0)
    new_events_persisted = mapped_column(Integer, nullable=False, default=0)
    terminal_status_detected = mapped_column(String(64), nullable=True)
    response_format = mapped_column(String(64), nullable=True)
    duration_ms = mapped_column(Float, nullable=True)
