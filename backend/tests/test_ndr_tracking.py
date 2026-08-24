from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.ndr import NDRCase
from app.models.shipment_event import ShipmentEvent
from app.services.courier_platform.models import NormalizedShipmentStatus, TrackingResult
from app.services.ndr_tracking import enroll_case, poll_case, reconcile_persisted_events
from app.services.shipment_events import append_tracking_events


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def make_case(db, case_id="case-1", awb="AWB-1", provider="delhivery"):
    now = datetime.now(timezone.utc)
    case = NDRCase(id=case_id, source_identity=f"awb:{awb}", awb=awb, provider=provider, order_id=f"order-{case_id}", order_number="325001", source_lifecycle="active", current_status="new", priority="medium", delivery_attempts=1, first_ndr_at=now, last_synced_at=now, products=[], cod_amount=0)
    db.add(case); db.commit(); enroll_case(case, now=now); db.commit()
    return case


def tracking(provider, scan, at="2026-08-25T10:00:00Z"):
    raw = {"raw": {"ShipmentData": [{"Shipment": {"Scans": [{"ScanDetail": {"Scan": scan, "ScanDateTime": at}}]}}]}} if provider == "delhivery" else None
    return TrackingResult(provider=provider, status=NormalizedShipmentStatus.UNKNOWN, provider_status=scan, raw_response=raw)


@pytest.mark.anyio
async def test_poll_needs_no_booking_row_and_deduplicates(db, monkeypatch):
    case = make_case(db); calls = []
    class Adapter:
        async def track_shipment(self, shipment):
            calls.append((shipment["provider"], shipment["awb"])); return tracking("delhivery", "In Transit")
    monkeypatch.setattr("app.services.ndr_tracking.courier_registry.get", lambda provider: Adapter())
    assert await poll_case(db, case) == "in_transit_reattempt"
    assert await poll_case(db, case) == "in_transit_reattempt"
    assert calls == [("delhivery", "AWB-1")] * 2
    assert len(db.scalars(select(ShipmentEvent)).all()) == 1


@pytest.mark.anyio
async def test_provider_failure_never_resolves(db, monkeypatch):
    case = make_case(db)
    class Adapter:
        async def track_shipment(self, shipment): raise RuntimeError("read failed")
    monkeypatch.setattr("app.services.ndr_tracking.courier_registry.get", lambda provider: Adapter())
    assert await poll_case(db, case) == "provider_error"
    db.refresh(case)
    assert case.resolution_outcome is None and case.tracking_next_attempt_at is not None


@pytest.mark.anyio
@pytest.mark.parametrize(("scan", "classification", "outcome"), [("RTO In Transit", "rto_in_progress", None), ("RTO Delivered", "rto_complete", "rto_confirmed")])
async def test_rto_lifecycle(db, monkeypatch, scan, classification, outcome):
    case = make_case(db)
    class Adapter:
        async def track_shipment(self, shipment): return tracking("delhivery", scan)
    monkeypatch.setattr("app.services.ndr_tracking.courier_registry.get", lambda provider: Adapter())
    assert await poll_case(db, case) == classification
    db.refresh(case)
    assert case.resolution_outcome == outcome
    assert (case.tracking_next_attempt_at is None) == (outcome == "rto_confirmed")


def test_exact_provider_awb_and_stale_event_protection(db):
    case = make_case(db)
    append_tracking_events(db, order_id="wrong", shipment={"provider": "shiprocket", "awb": case.awb}, result=TrackingResult(provider="shiprocket", status=NormalizedShipmentStatus.DELIVERED, provider_status="Delivered"), source="test")
    assert reconcile_persisted_events(db, case) == "unknown" and case.resolution_outcome is None
    append_tracking_events(db, order_id=case.order_id, shipment={"provider": "delhivery", "awb": case.awb}, result=tracking("delhivery", "Delivered", "2026-08-25T12:00:00Z"), source="test")
    assert reconcile_persisted_events(db, case) == "delivered"
    db.commit()
    append_tracking_events(db, order_id=case.order_id, shipment={"provider": "delhivery", "awb": case.awb}, result=tracking("delhivery", "In Transit", "2026-08-24T12:00:00Z"), source="test")
    assert reconcile_persisted_events(db, case) == "delivered" and case.resolution_outcome == "delivered"
