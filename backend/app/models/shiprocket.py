from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class ShiprocketShipment(Base):
    __tablename__ = "shiprocket_shipments"

    order_id = mapped_column(String(32), primary_key=True)
    provider = mapped_column(String(32), nullable=True)
    provider_order_id = mapped_column(String(128), nullable=True)
    shiprocket_order_id = mapped_column(String(64), nullable=True)
    shipment_id = mapped_column(String(64), nullable=True)
    awb = mapped_column(String(64), nullable=True)
    courier_name = mapped_column(String(128), nullable=True)
    courier_id = mapped_column(String(64), nullable=True)
    booking_status = mapped_column(String(64), nullable=True)
    booking_mode = mapped_column(String(32), nullable=True)
    booking_freight = mapped_column(Float, nullable=True)
    booking_operator = mapped_column(String(128), nullable=True)
    booking_note = mapped_column(Text, nullable=True)
    booked_at = mapped_column(DateTime(timezone=True), nullable=True)
    latest_status = mapped_column(String(128), nullable=True)
    normalized_status = mapped_column(String(64), nullable=True)
    courier_service = mapped_column(String(128), nullable=True)
    latest_tracking_at = mapped_column(DateTime(timezone=True), nullable=True)
    latest_scan = mapped_column(Text, nullable=True)
    terminal_status = mapped_column(String(64), nullable=True)
    last_synced_at = mapped_column(DateTime(timezone=True), nullable=True)
    tracking_url = mapped_column(Text, nullable=True)
    label_url = mapped_column(Text, nullable=True)
    label_format = mapped_column(String(16), nullable=True)
    expected_delivery_date = mapped_column(String(64), nullable=True)
    delivered_at = mapped_column(DateTime(timezone=True), nullable=True)
    address_sync_status = mapped_column(String(64), nullable=True)
    address_sync_error = mapped_column(Text, nullable=True)
    package_weight_kg = mapped_column(Float, nullable=True)
    package_length_cm = mapped_column(Float, nullable=True)
    package_breadth_cm = mapped_column(Float, nullable=True)
    package_height_cm = mapped_column(Float, nullable=True)
    selected_courier_id = mapped_column(String(64), nullable=True)
    selected_courier_name = mapped_column(String(128), nullable=True)
    shopify_fulfillment_id = mapped_column(String(128), nullable=True)
    shopify_fulfillment_status = mapped_column(String(64), nullable=True)
    shopify_fulfillment_sync_status = mapped_column(String(32), nullable=True)
    shopify_fulfillment_synced_at = mapped_column(DateTime(timezone=True), nullable=True)
    shopify_fulfillment_sync_error = mapped_column(Text, nullable=True)
    shopify_tracking_number = mapped_column(String(128), nullable=True)
    shopify_tracking_url = mapped_column(Text, nullable=True)
    shopify_customer_notified = mapped_column(Boolean, nullable=True)
    label_print_status = mapped_column(String(32), nullable=True)
    label_first_printed_at = mapped_column(DateTime(timezone=True), nullable=True)
    label_last_printed_at = mapped_column(DateTime(timezone=True), nullable=True)
    label_last_printed_by = mapped_column(String(128), nullable=True)
    label_print_count = mapped_column(Integer, nullable=False, default=0)
    last_print_batch_id = mapped_column(String(64), nullable=True)
    label_tracking_activated_at = mapped_column(DateTime(timezone=True), nullable=True)
    dispatch_status = mapped_column(String(32), nullable=True)
    manifested_at = mapped_column(DateTime(timezone=True), nullable=True)
    manifested_by = mapped_column(String(128), nullable=True)
    raw_provider_response = mapped_column(Text, nullable=True)
    booking_confidence = mapped_column(String(32), nullable=True)
    reconciliation_status = mapped_column(String(32), nullable=True)
    reconciliation_error = mapped_column(Text, nullable=True)
    ndr_reason = mapped_column(Text, nullable=True)
    ndr_attempt = mapped_column(Integer, nullable=True)
    ndr_remarks = mapped_column(Text, nullable=True)
    ndr_operator_action = mapped_column(Text, nullable=True)
    address_confidence_score = mapped_column(Float, nullable=True)
    address_confidence_category = mapped_column(String(64), nullable=True)
    address_confidence_source = mapped_column(String(64), nullable=True)
    address_confidence_checked_at = mapped_column(DateTime(timezone=True), nullable=True)
    engage_order_id = mapped_column(String(64), nullable=True)
    order_confirmation = mapped_column(JSON, nullable=True)
    order_confirmation_message = mapped_column(Text, nullable=True)
    address_confirmation = mapped_column(JSON, nullable=True)
    address_confirmation_message = mapped_column(Text, nullable=True)
    cod_to_prepaid = mapped_column(JSON, nullable=True)
    cod_to_prepaid_message = mapped_column(Text, nullable=True)
    engage_last_synced_at = mapped_column(DateTime(timezone=True), nullable=True)
    engage_raw_status = mapped_column(JSON, nullable=True)


class LabelPrintBatch(Base):
    __tablename__ = "label_print_batches"

    id = mapped_column(String(64), primary_key=True)
    provider = mapped_column(String(32), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)
    created_by = mapped_column(String(128), nullable=False)
    status = mapped_column(String(32), nullable=False)
    confirmed_at = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by = mapped_column(String(128), nullable=True)
    pdf_cache_path = mapped_column(Text, nullable=True)


class LabelPrintBatchItem(Base):
    __tablename__ = "label_print_batch_items"

    batch_id = mapped_column(String(64), primary_key=True)
    order_id = mapped_column(String(32), primary_key=True)
    position = mapped_column(Integer, nullable=False)
    status = mapped_column(String(32), nullable=False)


class CourierWebhookEvent(Base):
    __tablename__ = "courier_webhook_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_courier_webhook_provider_event"),)

    id = mapped_column(String(64), primary_key=True)
    provider = mapped_column(String(32), nullable=False)
    provider_event_id = mapped_column(String(128), nullable=False)
    order_id = mapped_column(String(32), nullable=True)
    payload_hash = mapped_column(String(64), nullable=False)
    received_at = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at = mapped_column(DateTime(timezone=True), nullable=True)
    status = mapped_column(String(32), nullable=False)
    error = mapped_column(Text, nullable=True)


class OrderAddressState(Base):
    """Small durable authority for the address revision; operational history stays in JSON."""
    __tablename__ = "order_address_states"

    order_id = mapped_column(String(32), primary_key=True)
    revision = mapped_column(Integer, nullable=False, default=0)
    address = mapped_column(JSON, nullable=True)
    verified = mapped_column(Boolean, nullable=False, default=False)
    sync_lease_revision = mapped_column(Integer, nullable=True)
    sync_lease_token = mapped_column(String(64), nullable=True)
    sync_lease_expires_at = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status = mapped_column(String(32), nullable=False, default="not_started")
    sync_error = mapped_column(Text, nullable=True)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False)


class AddressSyncOperation(Base):
    __tablename__ = "address_sync_operations"
    __table_args__ = (UniqueConstraint("order_id", "revision", name="uq_address_sync_order_revision"),)

    id = mapped_column(String(64), primary_key=True)
    order_id = mapped_column(String(32), nullable=False, index=True)
    revision = mapped_column(Integer, nullable=False)
    address = mapped_column(JSON, nullable=False)
    status = mapped_column(String(32), nullable=False)  # pending/running/succeeded/failed/superseded
    attempts = mapped_column(Integer, nullable=False, default=0)
    error = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token = mapped_column(String(64), nullable=True)


class BookingReservation(Base):
    """One durable booking command per order. It deliberately survives process restarts."""
    __tablename__ = "booking_reservations"

    order_id = mapped_column(String(32), primary_key=True)
    idempotency_key = mapped_column(String(64), nullable=False, unique=True)
    provider = mapped_column(String(32), nullable=False)
    context_hash = mapped_column(String(128), nullable=False)
    state = mapped_column(String(32), nullable=False)  # reserved/submitted/succeeded/failed/uncertain
    attempts = mapped_column(Integer, nullable=False, default=0)
    provider_request_started_at = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    error = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False)
