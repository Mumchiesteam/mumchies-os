from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class NormalizedShipmentStatus(StrEnum):
    CREATED = "created"
    BOOKED = "booked"
    PICKUP_SCHEDULED = "pickup_scheduled"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    NDR = "ndr"
    RTO = "rto"
    CANCELLED = "cancelled"
    EXCEPTION = "exception"
    UNKNOWN = "unknown"


class BookingConfidence(StrEnum):
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    RECONCILED = "reconciled"


class ReconciliationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class LabelFormat(StrEnum):
    PDF = "pdf"
    PNG = "png"
    JPEG = "jpeg"


class ProviderCapabilities(BaseModel):
    serviceability: bool = False
    booking: bool = False
    tracking: bool = False
    cancellation: bool = False
    labels: bool = False
    ndr: bool = False
    webhooks: bool = False
    polling: bool = True


class QuoteResult(BaseModel):
    provider: str
    service_id: str
    courier_name: str
    serviceable: bool
    charges: float | None = None
    cod_charge: float | None = None
    estimated_delivery_days: int | None = None
    expected_delivery_date: str | None = None
    service_type: str | None = None
    reason: str | None = None
    raw_response: dict[str, Any] | list[Any] | None = None


class ServiceabilityResult(BaseModel):
    provider: str
    serviceable: bool
    quotes: list[QuoteResult] = Field(default_factory=list)
    reason: str | None = None


class BookingResult(BaseModel):
    provider: str
    provider_order_id: str | None = None
    shipment_id: str | None = None
    awb: str | None = None
    tracking_url: str | None = None
    service: str | None = None
    status: NormalizedShipmentStatus = NormalizedShipmentStatus.UNKNOWN
    booked_at: datetime | None = None
    label_url: str | None = None
    label_format: LabelFormat | None = None
    confidence: BookingConfidence = BookingConfidence.CONFIRMED
    reconciliation_status: ReconciliationStatus = ReconciliationStatus.NOT_REQUIRED
    existing: bool = False
    raw_response: dict[str, Any] | list[Any] | None = None


class TrackingResult(BaseModel):
    provider: str
    status: NormalizedShipmentStatus
    provider_status: str | None = None
    latest_scan: str | None = None
    latest_tracking_at: datetime | None = None
    tracking_url: str | None = None
    terminal: bool = False
    ndr_reason: str | None = None
    ndr_attempt: int | None = None
    courier_remarks: str | None = None
    raw_response: dict[str, Any] | list[Any] | None = None


class CancellationResult(BaseModel):
    provider: str
    status: str
    cancelled: bool = False
    provider_status: str | None = None
    message: str
    raw_response: dict[str, Any] | list[Any] | None = None


class LabelResult(BaseModel):
    provider: str
    content: bytes
    format: LabelFormat
    content_type: str
    source_url: str | None = None


class ShipmentTimelineEvent(BaseModel):
    provider: str
    action: str
    timestamp: datetime
    operator: str | None = None
    status: NormalizedShipmentStatus | None = None
    details: dict[str, Any] = Field(default_factory=dict)
