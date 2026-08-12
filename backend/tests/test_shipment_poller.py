from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models.shipment_event import ShipmentEvent
from app.models.ndr import NDRCase
from app.models.shipment_poll import ShipmentPollAttempt, ShipmentPollRun
from app.repositories.shiprocket import get_shipment, upsert_shipment
from app.services.courier_platform.base import ProviderError
from app.services.courier_platform.models import NormalizedShipmentStatus, TrackingResult
from app.services.shipment_poller import (
    _error_category, _run_lock, cleanup_poller_audit, eligible_shipments, poller_audit_status, poller_status, resolve_visible_order_number, run_tracking_poll,
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


def test_active_ndr_awb_is_prioritized_inside_bounded_tracking_batch(sessions):
    add_shipment(sessions,"ordinary",awb="ORDINARY")
    add_shipment(sessions,"ndr",awb="SF36981898586")
    now=datetime.now(timezone.utc)
    with sessions() as db:
        db.add(NDRCase(id="ndr-case",source_identity="awb:SF36981898586",awb="SF36981898586",provider="shadowfax",order_number="323027",source_lifecycle="active",current_status="courier_pending",priority="medium",delivery_attempts=2,first_ndr_at=now,last_synced_at=now,products=[],cod_amount=0));db.commit()
        assert [shipment.awb for shipment in eligible_shipments(db,batch_size=1)]==["SF36981898586"]


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
        runs = db.scalars(select(ShipmentPollRun).order_by(ShipmentPollRun.started_at)).all()
        assert len(runs) == 2 and runs[0].status == "completed"
        assert runs[0].provider_counts["shiprocket"] == {"attempted": 3, "succeeded": 2, "failed": 1, "new_events": 6}
        attempts = db.scalars(select(ShipmentPollAttempt).where(ShipmentPollAttempt.run_id == runs[0].run_id)).all()
        assert len(attempts) == 3
        success = next(item for item in attempts if item.order_id == "good")
        assert success.result == "success" and success.events_returned == 3 and success.new_events_persisted == 3
        assert success.response_format == "shiprocket_tracking_data" and success.duration_ms is not None
        failure = next(item for item in attempts if item.order_id == "failed")
        assert failure.result == "failure" and failure.error_category == "rate_limited" and failure.http_status == 429
        assert failure.completed_at is not None
        audit = poller_audit_status(db)
        assert audit["provider_coverage"]["shiprocket"]["attempted"] == 6
        assert audit["failure_breakdown"] == {"rate_limited": 2}
        assert audit["event_count_by_provider"] == {"shiprocket": 6}
        assert audit["provider_timestamped_events"] == {"shiprocket": 6}


class DeliveredAdapter:
    provider = "delhivery"

    async def track_shipment(self, shipment):
        return TrackingResult(
            provider="delhivery", status=NormalizedShipmentStatus.DELIVERED, provider_status="Delivered",
            terminal=True, raw_response={"delivered_at": datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc), "raw": {"ShipmentData": [{"Shipment": {"Scans": [
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
    assert first["shipments_succeeded"] == 1 and first["shipments_failed"] == 0
    assert second["shipments_attempted"] == 0
    status = poller_status()
    assert status["shipments_attempted"] == 0
    assert status["providers"]["shadowfax"] is False
    assert status["last_poll_started"] and status["last_poll_completed"]
    with sessions() as db:
        shipment = get_shipment(db, "delivered-next")
        assert shipment.normalized_status == "delivered" and shipment.terminal_status == "delivered"
        assert '"delivered_at":"2026-08-04T09:00:00+00:00"' in shipment.raw_provider_response
        assert len(db.scalars(select(ShipmentEvent).where(ShipmentEvent.order_id == "delivered-next")).all()) == 1
        attempts = db.scalars(select(ShipmentPollAttempt).where(ShipmentPollAttempt.order_id == "delivered-next")).all()
        assert len(attempts) == 1 and attempts[0].result == "success" and attempts[0].error_category is None


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


def test_genuine_malformed_response_is_still_classified():
    assert _error_category(TypeError("provider payload is not a mapping")) == ("malformed_response", False)


def test_retention_keeps_latest_100_runs_and_historical_runs_remain_queryable(sessions):
    now = datetime.now(timezone.utc)
    with sessions() as db:
        for index in range(105):
            run_id = uuid4().hex
            started = now - timedelta(hours=104 - index)
            db.add(ShipmentPollRun(
                run_id=run_id, started_at=started, completed_at=started + timedelta(minutes=1),
                total_attempted=1, total_succeeded=1, total_failed=0,
                new_events_persisted=0, provider_counts={"shiprocket": {"attempted": 1}}, status="completed",
            ))
            db.add(ShipmentPollAttempt(
                id=uuid4().hex, run_id=run_id, order_id=f"order-{index}", provider="shiprocket",
                attempted_at=started, completed_at=started + timedelta(seconds=1), result="success",
                events_returned=0, new_events_persisted=0,
            ))
        db.commit()
        cleanup_poller_audit(db, now=now, max_runs=100, retention_days=30)
        assert len(db.scalars(select(ShipmentPollRun)).all()) == 100
        assert len(db.scalars(select(ShipmentPollAttempt)).all()) == 100
        assert len(poller_audit_status(db, run_limit=10)["latest_runs"]) == 10


def test_error_summary_redacts_secrets_and_pii(sessions, monkeypatch):
    class UnsafeAdapter:
        provider = "shiprocket"

        async def track_shipment(self, shipment):
            raise ProviderError(
                "token=topsecret phone=9876543210 email=user@example.com",
                provider="shiprocket", operation="tracking", http_status=403,
            )

    add_shipment(sessions, "unsafe", awb="SAFE-AWB")
    monkeypatch.setattr("app.services.shipment_poller.courier_registry.get", lambda provider: UnsafeAdapter())
    # The synchronous test uses a dedicated event loop through asyncio.run.
    import asyncio
    asyncio.run(run_tracking_poll(sessions, sleep=lambda _: _done()))
    with sessions() as db:
        attempt = db.scalar(select(ShipmentPollAttempt).where(ShipmentPollAttempt.order_id == "unsafe"))
        assert "topsecret" not in attempt.error_summary
        assert "9876543210" not in attempt.error_summary
        assert "user@example.com" not in attempt.error_summary


async def _done():
    return None


def test_visible_shopify_order_number_never_uses_provider_order_id(sessions, monkeypatch):
    class SuccessAdapter:
        provider = "shiprocket"

        async def track_shipment(self, shipment):
            return TrackingResult(provider="shiprocket", status=NormalizedShipmentStatus.IN_TRANSIT, provider_status="In Transit")

    shipment = add_shipment(sessions, "6854925719999", awb="AWB-PROVIDER")
    assert shipment.provider_order_id == "REF-6854925719999"
    assert resolve_visible_order_number(shipment.order_id, {shipment.order_id: "324999"}) == "324999"
    assert resolve_visible_order_number(shipment.order_id, None) is None
    monkeypatch.setattr("app.services.shipment_poller.courier_registry.get", lambda provider: SuccessAdapter())
    import asyncio
    asyncio.run(run_tracking_poll(
        sessions, sleep=lambda _: _done(), canonical_order_numbers={shipment.order_id: "324999"},
    ))
    with sessions() as db:
        attempt = db.scalar(select(ShipmentPollAttempt).where(ShipmentPollAttempt.order_id == shipment.order_id))
        assert attempt.order_number == "324999"
        assert attempt.order_number != shipment.provider_order_id
