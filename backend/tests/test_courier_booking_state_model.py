from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.api.routes.orders import _canonical_shipment_readback
from app.repositories.shiprocket import get_shipment, snapshot, upsert_shipment
from app.schemas.orders import ExternalTracking, ShopifyOrder
from app.services.courier_platform.base import ProviderError
from app.services.courier_platform.models import BookingResult, NormalizedShipmentStatus
from app.services.courier_platform.service import CourierPlatformService
from app.services.shipment_status import (
    has_persisted_provider_booking_evidence,
    has_uncertain_provider_booking,
    merge_shopify_fulfillment_evidence,
)
from app.services.shiprocket import ShiprocketPersistenceError, ShiprocketService


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'state.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close(); engine.dispose()


def eligible_order(payment_status: str):
    return SimpleNamespace(payment_status=payment_status, fulfillment_status=None, shopify_status=None,
                           cancelled_at=None, tags=[], phone="9999999999", shipping_address={"pincode": "110001", "phone": "9999999999"})


def eligible_ops():
    return {"address_verified": True, "call_logs": [{"result": "Confirmed"}],
            "package_details": {"weight_kg": .5, "length_cm": 10, "breadth_cm": 10, "height_cm": 10}}


@pytest.mark.parametrize("payment_status", ["paid", "pending"])
def test_fresh_prepaid_and_cod_are_bookable_without_shipment(payment_status):
    result = ShiprocketService(email="x", password="x", pickup_location="Warehouse").evaluate_booking_eligibility(
        eligible_order(payment_status), eligible_ops(), None)
    assert result.eligible and not result.shipment_exists and result.shipment_snapshot is None


@pytest.mark.parametrize("row", [
    {"provider_order_id": "QUOTE"}, {"shiprocket_order_id": "ORDER"},
    {"selected_courier_id": "42"}, {"provider_order_id": "FAILED", "booking_status": "booking_failed"},
])
def test_quote_selection_failed_and_placeholder_rows_are_not_evidence(row):
    assert not has_persisted_provider_booking_evidence(row)
    assert not has_uncertain_provider_booking(row)


@pytest.mark.parametrize("row", [
    {"awb": "A"}, {"shipment_id": "S"}, {"shopify_tracking_number": "T"},
    {"provider_order_id": "P", "booking_status": "booked"},
])
def test_genuine_identifiers_or_confirmed_provider_status_are_evidence(row):
    assert has_persisted_provider_booking_evidence(row)


def test_booking_initiated_failed_and_uncertain_are_separate():
    assert not has_uncertain_provider_booking({"booking_status": "booking_initiated"})
    assert not has_uncertain_provider_booking({"booking_status": "booking_failed"})
    assert has_uncertain_provider_booking({"booking_status": "booking_uncertain"})


def test_order_323976_class_reopens_from_genuine_shopify_evidence_without_fabrication():
    external = ExternalTracking(provider="Shiprocket", awb="REAL-AWB", status="in_transit", tracking_url="https://track.example/REAL-AWB")
    merged = merge_shopify_fulfillment_evidence(None, external)
    assert (merged["provider"], merged["courier_name"], merged["awb"]) == ("Shiprocket", "Shiprocket", "REAL-AWB")
    assert (merged["booking_status"], merged["latest_status"], merged["evidence_source"]) == ("confirmed_external", "in_transit", "shopify_fulfillment")
    assert merged.get("shipment_id") is None and merged.get("booked_at") is None
    assert has_persisted_provider_booking_evidence(merged)


def test_shopify_evidence_completes_same_internal_record_without_replacing_fields():
    local = {"provider": "shiprocket", "shipment_id": "SHIP", "booking_status": "booked", "courier_name": "Courier X"}
    merged = merge_shopify_fulfillment_evidence(local, ExternalTracking(provider="Shiprocket", awb="AWB", status="shipped"))
    assert (merged["shipment_id"], merged["courier_name"], merged["awb"]) == ("SHIP", "Courier X", "AWB")
    assert merged["evidence_source"] == "internal_and_shopify"


class Adapter:
    provider = "test"
    calls = 0
    async def reconcile_booking(self, _merchant_order_id): return None
    async def create_booking(self, _request):
        self.calls += 1
        return BookingResult(provider="test", provider_order_id="P", shipment_id="S", awb="A",
                             service="Surface", status=NormalizedShipmentStatus.BOOKED)


@pytest.mark.anyio
async def test_placeholder_does_not_block_and_success_persists_complete_canonical_record(db):
    upsert_shipment(db, "1", provider="test", provider_order_id="OLD", booking_status="booking_failed")
    adapter = Adapter()
    result = await CourierPlatformService().book(db, order_id="1", merchant_order_id="M", adapter=adapter, request={}, operator="Operator")
    stored = snapshot(get_shipment(db, "1"))
    assert not result["existing"] and adapter.calls == 1
    assert (stored["provider"], stored["courier_name"], stored["courier_service"]) == ("test", "Surface", "Surface")
    assert (stored["awb"], stored["shipment_id"], stored["provider_order_id"]) == ("A", "S", "P")
    assert stored["booking_status"] == "booked" and stored["booked_at"] is not None and stored["latest_status"] == "booked"


@pytest.mark.anyio
async def test_reopen_and_duplicate_guard_use_identical_canonical_record(db):
    adapter = Adapter()
    first = await CourierPlatformService().book(db, order_id="2", merchant_order_id="M2", adapter=adapter, request={}, operator="Operator")
    reopened = snapshot(get_shipment(db, "2"))
    second = await CourierPlatformService().book(db, order_id="2", merchant_order_id="M2", adapter=adapter, request={}, operator="Operator")
    assert first["shipment"] == reopened == second["shipment"] and second["existing"]
    assert adapter.calls == 1


@pytest.mark.anyio
async def test_failed_and_uncertain_outcomes_are_distinct_and_only_uncertain_blocks(db):
    class Failed(Adapter):
        async def create_booking(self, _request): raise ProviderError("rejected", provider="test", operation="booking")
    with pytest.raises(ProviderError):
        await CourierPlatformService().book(db, order_id="f", merchant_order_id="F", adapter=Failed(), request={}, operator="Operator")
    assert snapshot(get_shipment(db, "f"))["booking_status"] == "booking_failed"

    class Uncertain(Adapter):
        async def create_booking(self, _request): self.calls += 1; raise TimeoutError("unknown")
    adapter = Uncertain()
    with pytest.raises(TimeoutError):
        await CourierPlatformService().book(db, order_id="u", merchant_order_id="U", adapter=adapter, request={}, operator="Operator")
    assert snapshot(get_shipment(db, "u"))["booking_status"] == "booking_uncertain"
    with pytest.raises(ProviderError, match="uncertain outcome"):
        await CourierPlatformService().book(db, order_id="u", merchant_order_id="U", adapter=adapter, request={}, operator="Operator")
    assert adapter.calls == 1


@pytest.mark.anyio
async def test_readback_reconciles_incomplete_shiprocket_row_without_booking(monkeypatch, db):
    upsert_shipment(db, "323976", provider="shiprocket", provider_order_id="323976")
    order = ShopifyOrder(
        order_id="323976", order_number="323976", created_date="2026-08-01T00:00:00Z",
        products=[], total_amount=0, fulfillment_status="fulfilled", tags=[],
        external_tracking=ExternalTracking(provider="Shiprocket", awb="AWB-323976", status="shipped"),
    )
    calls = []
    async def reconcile(_self, session, local_order_id, channel_order_id, expected_shipment_id=None):
        calls.append((local_order_id, channel_order_id, expected_shipment_id))
        return snapshot(upsert_shipment(
            session, local_order_id, provider="shiprocket", provider_order_id=channel_order_id,
            shiprocket_order_id="SR-ORDER", shipment_id="SR-SHIPMENT", awb="AWB-323976",
            courier_name="Delhivery Surface", courier_service="Surface", booking_status="booked",
            booked_at=datetime(2026, 8, 1, tzinfo=timezone.utc), latest_status="Shipped",
        ))
    monkeypatch.setattr(ShiprocketService, "reconcile_existing_shipment", reconcile)
    result = await _canonical_shipment_readback(order, {"selected_courier": {"provider": "shiprocket"}}, db)
    assert calls == [("323976", "323976", None)]
    assert (result["provider"], result["courier_name"], result["awb"]) == ("shiprocket", "Delhivery Surface", "AWB-323976")
    assert (result["shipment_id"], result["provider_order_id"], result["booking_status"]) == ("SR-SHIPMENT", "323976", "booked")
    assert result["booked_at"] and result["latest_status"] == "Shipped"
    assert result["readback_reconciliation_status"] == "reconciled"


@pytest.mark.anyio
async def test_provider_success_local_persistence_failure_is_distinct_and_never_assigns_or_rebooks(monkeypatch):
    service = ShiprocketService(email="x", password="x", pickup_location="Warehouse")
    service.create_order = lambda _payload: None
    async def created(_payload):
        return {"order_id": "SR-ORDER", "shipment_id": "SR-SHIPMENT", "awb_code": "AWB-1"}
    service.create_order = created
    assigned = False
    async def assign(*_args):
        nonlocal assigned; assigned = True
    service.assign_courier_and_generate_awb = assign
    class BrokenDB:
        rolled_back = False
        def get(self, *_args): return None
        def add(self, *_args): raise RuntimeError("database unavailable")
        def rollback(self): self.rolled_back = True
    broken = BrokenDB()
    with pytest.raises(ShiprocketPersistenceError) as caught:
        await service.create_shipment(broken, "1", {"order_id": "1"}, "42")
    assert caught.value.safe_details["provider_success"] is True
    assert caught.value.safe_details["rebooking_safe"] is False
    assert caught.value.safe_details["shipment_id"] == "SR-SHIPMENT"
    assert broken.rolled_back and not assigned
