from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import pytest

from app.db.base import Base
from app.models.shipment_event import ShipmentEvent
from app.repositories.shiprocket import get_shipment, upsert_shipment
from app.services.courier_platform.models import NormalizedShipmentStatus, TrackingResult
from app.services.courier_platform.service import CourierPlatformService
from app.api.routes.courier_platform import courier_shipment_events
from app.services.shipment_events import append_tracking_events, normalize_event_status, shipment_event_history


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.parametrize(("provider_status", "expected"), [
    ("AWB Assigned", "booked"), ("Pickup Scheduled", "pickup_scheduled"),
    ("Picked Up", "picked_up"), ("In Transit", "in_transit"),
    ("Out For Delivery", "out_for_delivery"), ("Delivery Attempted", "delivery_attempted"),
    ("NDR", "ndr"), ("Re-attempt scheduled", "reattempt"), ("Delivered", "delivered"),
    ("RTO Initiated", "rto_initiated"), ("RTO In Transit", "rto_in_transit"),
    ("RTO Delivered", "rto_delivered"), ("Cancelled", "cancelled"), ("Unmapped", "unknown"),
])
def test_event_status_normalization(provider_status, expected):
    assert normalize_event_status(provider_status) == expected


def test_shiprocket_multiple_events_are_append_only_and_deduplicated(db):
    shipment = upsert_shipment(
        db, "order-1", provider="shiprocket", provider_order_id="1001",
        shipment_id="S1", awb="AWB1", courier_name="Ekart Surface",
        booking_status="booked", latest_status="In Transit",
    )
    result = TrackingResult(
        provider="shiprocket", status=NormalizedShipmentStatus.IN_TRANSIT,
        provider_status="In Transit",
        raw_response={"tracking_data": {"shipment_track_activities": [
            {"date": "2026-08-01 10:00:00", "status": "AWB Assigned", "activity": "Shipment booked", "location": "BLR"},
            {"date": "2026-08-02 11:00:00", "status": "In Transit", "activity": "Reached hub", "location": "Kolkata"},
        ]}},
    )
    context = {
        "provider": shipment.provider, "provider_order_id": shipment.provider_order_id,
        "shipment_id": shipment.shipment_id, "awb": shipment.awb, "courier_name": shipment.courier_name,
    }

    first = append_tracking_events(db, order_id="order-1", order_number="324000", shipment=context, result=result, source="api_poll")
    second = append_tracking_events(db, order_id="order-1", order_number="324000", shipment=context, result=result, source="api_poll")

    assert [event.normalized_status for event in first] == ["booked", "in_transit"]
    assert second == []
    assert db.scalars(select(ShipmentEvent)).all() == first
    assert get_shipment(db, "order-1").latest_status == "In Transit"


@pytest.mark.parametrize(("provider", "raw", "expected"), [
    ("delhivery", {"raw": {"ShipmentData": [{"Shipment": {"Scans": [{"ScanDetail": {"Scan": "Out for Delivery", "ScanType": "UD", "ScanDateTime": "2026-08-03T08:00:00Z", "ScannedLocation": "Kolkata"}}]}}]}}, "out_for_delivery"),
    ("shadowfax", {"provider_response": {"tracking_details": [{"created": "2026-08-03T09:00:00Z", "status_id": "delivered", "location": "Kolkata", "remarks": "Delivered"}]}}, "delivered"),
])
def test_provider_specific_event_extraction(db, provider, raw, expected):
    result = TrackingResult(provider=provider, status=NormalizedShipmentStatus.UNKNOWN, raw_response=raw)
    events = append_tracking_events(
        db, order_id=f"{provider}-1", shipment={"provider": provider, "awb": f"{provider}-awb"},
        result=result, source="api_poll",
    )
    assert len(events) == 1 and events[0].normalized_status == expected
    assert events[0].provider_event_at is not None


def test_missing_provider_timestamp_remains_null_and_raw_pii_is_sanitized(db):
    result = TrackingResult(
        provider="shiprocket", status=NormalizedShipmentStatus.NDR, provider_status="NDR",
        raw_response={"tracking_data": {"shipment_track_activities": [{
            "status": "NDR", "activity": "Customer unavailable", "customer_name": "Private Name", "token": "secret",
        }]}},
    )
    event = append_tracking_events(
        db, order_id="order-2", shipment={"provider": "shiprocket", "awb": "AWB2"},
        result=result, source="api_poll",
    )[0]
    assert event.provider_event_at is None
    history = shipment_event_history(db, "order-2")
    assert history[0]["recorded_at"] is not None
    assert history[0]["raw_provider_event"]["customer_name"] == "[REDACTED]"
    assert history[0]["raw_provider_event"]["token"] == "[REDACTED]"


@pytest.mark.anyio
async def test_read_only_event_history_endpoint(db):
    result = TrackingResult(provider="shiprocket", status=NormalizedShipmentStatus.BOOKED, provider_status="Booked")
    append_tracking_events(
        db, order_id="order-debug", shipment={"provider": "shiprocket", "awb": "DEBUG-AWB"},
        result=result, source="historical_sync", order_number="324099",
    )
    response = await courier_shipment_events("order-debug", db)
    assert response["total"] == 1
    assert response["events"][0]["order_number"] == "324099"


@pytest.mark.anyio
async def test_tracking_refresh_appends_events_without_changing_snapshot_contract(db):
    upsert_shipment(
        db, "order-3", provider="delhivery", provider_order_id="324003",
        shipment_id="D1", awb="D1", courier_name="Delhivery Surface",
        booking_status="booked", latest_status="Manifested",
    )

    class Adapter:
        provider = "delhivery"

        async def track_shipment(self, _shipment):
            return TrackingResult(
                provider="delhivery", status=NormalizedShipmentStatus.OUT_FOR_DELIVERY,
                provider_status="Out for Delivery", latest_scan="Kolkata Hub",
                raw_response={"raw": {"ShipmentData": [{"Shipment": {"Scans": [{"ScanDetail": {
                    "Scan": "Out for Delivery", "ScanDateTime": "2026-08-04T08:00:00Z", "ScannedLocation": "Kolkata Hub",
                }}]}}]}},
            )

    service = CourierPlatformService()
    first = await service.track(db, order_id="order-3", adapter=Adapter(), operator="Owner")
    second = await service.track(db, order_id="order-3", adapter=Adapter(), operator="Owner")

    assert first["latest_status"] == "Out for Delivery"
    assert second["normalized_status"] == "out_for_delivery"
    assert len(shipment_event_history(db, "order-3")) == 1
