from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models.shipment_event import ShipmentEvent
from app.repositories.shiprocket import get_shipment, upsert_shipment
from app.services.courier_platform.base import ProviderError
from app.services.courier_platform.models import NormalizedShipmentStatus, TrackingResult
from app.services.shipment_poller import (
    _error_category, _run_lock, eligible_shipments, poller_status, run_tracking_poll,
    shipment_poll_eligible, shadowfax_polling_enabled,
)


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "shipment_tracking_poll_batch_size", 20)
    monkeypatch.setattr(settings, "shipment_tracking_poll_spacing_seconds", 0.0)
    monkeypatch.setattr(settings, "shadowfax_tracking_poll_enabled", False)
    monkeypatch.setattr("app.services.report_snapshots.SNAPSHOT_FILE", tmp_path / "poller-snapshots.json")
    return factory


def add_shipment(factory, order_id, *, provider="shiprocket", awb="AWB-1", booking_status="booked", latest_status="Booked", shipment_id="SHIP-1"):
    with factory() as db:
        return upsert_shipment(
            db, order_id, provider=provider, provider_order_id=f"REF-{order_id}", shipment_id=shipment_id,
            awb=awb, booking_status=booking_status, latest_status=latest_status,
        )


def test_eligibility_excludes_terminal_failed_placeholder_and_shadowfax(sessions):
    active = add_shipment(sessions, "active")
    delivered = add_shipment(sessions, "delivered", latest_status="Delivered")
    rto_done = add_shipment(sessions, "rto", latest_status="RTO Delivered")
    failed = add_shipment(sessions, "failed", booking_status="booking_failed")
    placeholder = add_shipment(sessions, "placeholder", awb=None, shipment_id=None, booking_status="new")
    shadowfax = add_shipment(sessions, "shadowfax", provider="shadowfax")
    assert shipment_poll_eligible(active)
    assert not shipment_poll_eligible(delivered)
    assert not shipment_poll_eligible(rto_done)
    assert not shipment_poll_eligible(failed)
    assert not shipment_poll_eligible(placeholder)
    assert not shipment_poll_eligible(shadowfax)
    assert not shadowfax_polling_enabled()


class HistoryAdapter:
    provider = "shiprocket"

    async def track_shipment(self, shipment):
        if shipment["awb"] == "FAIL-AWB":
            raise ProviderError("rate limited", provider="shiprocket", operation="tracking", retryable=True, http_status=429)
        return TrackingResult(
            provider="shiprocket", status=NormalizedShipmentStatus.IN_TRANSIT,
            provider_status="Mystery transit state" if shipment["awb"] == "UNKNOWN-AWB" else "In Transit",
            raw_response={"tracking_data": {"shipment_track_activities": [
                {"status": "AWB Assigned", "date": "2026-08-01 10:00:00", "activity": "Booked"},
                {"status": "Picked Up", "date": "2026-08-02 11:00:00", "activity": "Collected"},
                {"status": "Mystery transit state" if shipment["awb"] == "UNKNOWN-AWB" else "In Transit", "date": "2026-08-03 12:00:00", "activity": "Moving"},
            ]}},
        )


@pytest.mark.anyio
async def test_poll_ingests_history_deduplicates_preserves_timestamps_and_continues_after_failure(sessions, monkeypatch):
    add_shipment(sessions, "good", awb="GOOD-AWB")
    add_shipment(sessions, "failed", awb="FAIL-AWB")
    add_shipment(sessions, "unknown", awb="UNKNOWN-AWB")
    monkeypatch.setattr("app.services.shipment_poller.courier_registry.get", lambda provider: HistoryAdapter())

    first = await run_tracking_poll(sessions, sleep=lambda _: _done())
    second = await run_tracking_poll(sessions, sleep=lambda _: _done())

    assert first["shipments_attempted"] == 3
    assert first["shipments_succeeded"] == 2 and first["shipments_failed"] == 1
    assert first["rate_limit_failures"] == 1
    assert first["new_events_persisted"] == 6
    assert second["new_events_persisted"] == 0
    with sessions() as db:
        events = db.scalars(select(ShipmentEvent).order_by(ShipmentEvent.provider_event_at)).all()
        assert len(events) == 6
        assert events[0].provider_event_at is not None
        assert any(event.normalized_status == "unknown" for event in events)
        assert get_shipment(db, "good").latest_status == "In Transit"


class DeliveredAdapter:
    provider = "delhivery"

    async def track_shipment(self, shipment):
        return TrackingResult(
            provider="delhivery", status=NormalizedShipmentStatus.DELIVERED, provider_status="Delivered",
            terminal=True, raw_response={"raw": {"ShipmentData": [{"Shipment": {"Scans": [
                {"ScanDetail": {"Scan": "Delivered", "ScanDateTime": "2026-08-04T09:00:00Z"}},
            ]}}]}},
        )


@pytest.mark.anyio
async def test_terminal_result_stops_future_polling_and_health_counts(sessions, monkeypatch):
    add_shipment(sessions, "delivered-next", provider="delhivery", awb="DEL-AWB")
    monkeypatch.setattr("app.services.shipment_poller.courier_registry.get", lambda provider: DeliveredAdapter())
    first = await run_tracking_poll(sessions, sleep=lambda _: _done())
    with sessions() as db:
        assert eligible_shipments(db, batch_size=20) == []
    second = await run_tracking_poll(sessions, sleep=lambda _: _done())
    assert first["new_events_persisted"] == 1
    assert second["shipments_attempted"] == 0
    status = poller_status()
    assert status["shipments_attempted"] == 0
    assert status["providers"]["shadowfax"] is False
    assert status["last_poll_started"] and status["last_poll_completed"]


@pytest.mark.anyio
async def test_overlapping_run_is_prevented(sessions):
    await _run_lock.acquire()
    try:
        result = await run_tracking_poll(sessions, sleep=lambda _: _done())
    finally:
        _run_lock.release()
    assert result == {"state": "overlap_skipped", "overlap_prevented": True}


@pytest.mark.parametrize(("status", "category", "retryable"), [
    (401, "authentication", False), (403, "authentication", False),
    (404, "not_found", False), (429, "rate_limited", True),
    (503, "provider_5xx", True),
])
def test_provider_http_error_categories(status, category, retryable):
    error = ProviderError("safe", provider="shiprocket", operation="tracking", http_status=status)
    assert _error_category(error) == (category, retryable)


async def _done():
    return None
