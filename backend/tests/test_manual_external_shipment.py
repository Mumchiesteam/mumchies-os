from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import couriers
from app.api.routes.couriers import ManualExternalShipmentPayload
from app.db.base import Base
from app.models.shiprocket import ShiprocketShipment
from app.models.user import User
from app.repositories.shiprocket import snapshot
from app.services import order_operations
from app.services.order_operations import OrderOperationsStore
from app.services.shopify import ShopifyService
from tests.test_operations_upgrade import raw_order


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'manual.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try: yield session
    finally: session.close(); engine.dispose()


def request():
    return SimpleNamespace(state=SimpleNamespace(auth_user=User(username="operator", display_name="Sushil", password_hash="unused", role="operator", is_active=True)))


def order(order_id="1", number="325879"):
    value = raw_order(); value.update({"id": int(order_id), "name": f"#{number}", "order_number": int(number)})
    return ShopifyService._to_order(value)


@pytest.fixture()
def manual_context(monkeypatch, tmp_path):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def load(order_id, db): return order(order_id), {}, None
    monkeypatch.setattr(couriers, "_load_context", load)
    async def validate(_order, _provider, _awb, _confirmed): return "operator_confirmed", None
    monkeypatch.setattr(couriers, "_validate_manual_external_association", validate)
    sync_calls = []
    async def sync(db, current): sync_calls.append(current.order_id); return snapshot(db.get(ShiprocketShipment, current.order_id))
    monkeypatch.setattr(couriers, "_sync_shopify_after_booking", sync)
    cleanup_calls = []
    async def cleanup(*args): cleanup_calls.append(args); return {"status": "not_applicable"}
    monkeypatch.setattr(couriers, "_cleanup_unused_shiprocket_order", cleanup)
    return sync_calls, cleanup_calls


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["shiprocket", "delhivery", "shadowfax"])
async def test_manual_external_booking_persists_provenance_dispatch_and_fulfillment(provider, db, manual_context):
    sync_calls, cleanup_calls = manual_context
    result = await couriers.record_manual_external_shipment("1", ManualExternalShipmentPayload(provider=provider, awb=f"{provider}-AWB", reason="Order recreated / cloned externally", comment="Customer approved", operator_confirmed=True), request(), db)
    row = db.get(ShiprocketShipment, "1")
    assert (row.provider, row.awb, row.booking_status, row.booking_mode, row.dispatch_status) == (provider, f"{provider}-AWB", "booked", "manual_external_booking", "ready_to_ship")
    assert row.booking_operator == "Sushil" and "Order recreated / cloned externally" in row.booking_note
    assert result["shipment"]["awb"] == f"{provider}-AWB" and sync_calls == ["1"]
    assert bool(cleanup_calls) is (provider != "shiprocket")
    if provider == "shiprocket": assert result["shiprocket_cleanup"]["reason"] == "manually_confirmed_shiprocket_is_the_real_shipment"
    event = OrderOperationsStore.get("1")["timeline_events"][-1]
    assert event["action"] == "manual_external_shipment_recorded" and event["details"]["provenance"] == "manual_external_booking"


@pytest.mark.anyio
async def test_duplicate_awb_cannot_cross_orders(db, manual_context):
    db.add(ShiprocketShipment(order_id="2", provider="shiprocket", awb="Same-AWB", booking_status="booked")); db.commit()
    with pytest.raises(Exception) as error:
        await couriers.record_manual_external_shipment("1", ManualExternalShipmentPayload(provider="delhivery", awb="same-awb", reason="OS booking issue", operator_confirmed=True), request(), db)
    assert getattr(error.value, "status_code", None) == 409 and "different order" in error.value.detail
    assert db.get(ShiprocketShipment, "1") is None


def test_manual_external_awb_is_mandatory():
    with pytest.raises(ValidationError): ManualExternalShipmentPayload(provider="shiprocket", awb="", reason="OS booking issue", operator_confirmed=True)


@pytest.mark.anyio
async def test_provider_order_mismatch_is_rejected_even_with_operator_confirmation(monkeypatch):
    class Adapter:
        async def reconcile_booking(self, _number): return SimpleNamespace(awb="AWB-FOR-OTHER-ORDER")
    monkeypatch.setattr(couriers.courier_registry, "get", lambda _provider: Adapter())
    with pytest.raises(Exception) as error:
        await couriers._validate_manual_external_association(order(), "delhivery", "EXPECTED-AWB", True)
    assert getattr(error.value, "status_code", None) == 409 and "Nothing was recorded" in error.value.detail
