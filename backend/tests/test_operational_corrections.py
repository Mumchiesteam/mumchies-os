from datetime import datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import couriers, orders
from app.api.routes.orders import AddressConfirmationPayload, CancellationPayload, SaveVerifyAddressPayload
from app.models.shiprocket import ShiprocketShipment
from app.db.base import Base
from app.services import order_operations
from app.services.order_operations import OrderOperationsStore
from app.services.shiprocket import ShiprocketAPIError, ShiprocketService
from app.services.shopify import ShopifySyncError
from app.services.shopify import ShopifyService
from tests.test_operations_upgrade import raw_order


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ops.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.mark.anyio
async def test_prepaid_address_comment_persists_operator_and_utc_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    record = await orders.add_address_confirmation_comment("1", AddressConfirmationPayload(comment="Gate confirmed", operator="Operator"))
    entry = record["address_confirmation_comments"][0]
    assert entry["comment"] == "Gate confirmed" and entry["operator"] == "Operator"
    assert datetime.fromisoformat(entry["timestamp"]).utcoffset().total_seconds() == 0
    assert record["call_logs"] == []


@pytest.mark.anyio
async def test_save_verify_address_validates_syncs_and_invalidates_old_verification(db, tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    OrderOperationsStore.verify_address("1", "Old", {"address_line1": "Old"}, "2026-07-25T00:00:00+00:00")
    calls = []

    async def context(_self, _id):
        return {"customer_id": "C1", "shipping_address": {"id": "A1", "address1": "12 Main Road", "city": "Delhi", "province": "Delhi", "zip": "110001", "phone": "9999999999"}}
    async def update_order(_self, _id, _address): calls.append("order")
    async def update_customer(_self, *_args, **kwargs): calls.append(("customer", kwargs["set_as_default"])); return {}
    monkeypatch.setattr(orders.ShopifyService, "get_order_address_context", context)
    monkeypatch.setattr(orders.ShopifyService, "update_order_shipping_address", update_order)
    monkeypatch.setattr(orders.ShopifyService, "update_customer_address", update_customer)
    payload = SaveVerifyAddressPayload(operator="Operator", customer_name="Customer", phone="9999999999", address_line1="12 Main Road", landmark="Near Park", city="Delhi", state="Delhi", pincode="110001")
    result = await orders.save_and_verify_address("1", payload, db)
    assert result["verified"] is True and result["operations"]["address_verified_by"] == "Operator"
    assert calls == ["order", ("customer", False)]
    OrderOperationsStore.save_address("1", {"address_line1": "Changed"}, operator="Operator")
    assert OrderOperationsStore.get("1")["address_verified"] is False


def preflight(*, shopify=True, shiprocket=True):
    return {"allowed": True, "shopify": {"exists": shopify}, "shiprocket": {"exists": shiprocket}, "shipment": {"exists": False}, "blocked_reason": None}


@pytest.mark.anyio
async def test_local_only_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def pf(_id, _db): return preflight(shopify=False, shiprocket=False)
    monkeypatch.setattr(orders, "_cancellation_preflight", pf)
    result = await orders.cancel_order("1", CancellationPayload(operator="Operator"), None)
    assert result["results"]["mumchies_os"]["status"] == "cancelled"
    assert result["results"]["shopify"]["status"] == "not_applicable"


@pytest.mark.anyio
async def test_shopify_and_shiprocket_cancellation_are_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def pf(_id, _db): return preflight()
    async def shopify_cancel(_self, _id): return {"status": "cancelled"}
    async def find(_self, _id): return {"id": 99, "status": "NEW", "shipments": []}
    async def shiprocket_cancel(_self, _order): return {}
    monkeypatch.setattr(orders, "_cancellation_preflight", pf)
    monkeypatch.setattr(orders.ShopifyService, "cancel_order", shopify_cancel)
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(orders.ShiprocketService, "cancel_unbooked_order", shiprocket_cancel)
    result = await orders.cancel_order("1", CancellationPayload(operator="Operator"), None)
    assert result["results"]["shopify"]["status"] == "cancelled"
    assert result["results"]["shiprocket"] == {"status": "cancelled", "cancel_on_channel": False}


@pytest.mark.anyio
async def test_partial_cancellation_failure_is_reported_and_local_state_survives(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def pf(_id, _db): return preflight(shopify=True, shiprocket=False)
    async def fail(_self, _id): raise ShopifySyncError("denied")
    monkeypatch.setattr(orders, "_cancellation_preflight", pf)
    monkeypatch.setattr(orders.ShopifyService, "cancel_order", fail)
    result = await orders.cancel_order("1", CancellationPayload(operator="Operator"), None)
    assert result["results"]["mumchies_os"]["status"] == "cancelled"
    assert result["results"]["shopify"] == {"status": "failed", "error": "denied"}


@pytest.mark.anyio
async def test_shiprocket_cancel_disables_channel_and_protects_awb(monkeypatch):
    service = ShiprocketService()
    seen = {}
    async def post(url, payload):
        seen.update({"url": url, "payload": payload})
        return httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(service, "_post", post)
    await service.cancel_unbooked_order({"id": 7, "status": "NEW", "shipments": []})
    assert seen["payload"] == {"ids": [7], "cancel_on_channel": False}
    with pytest.raises(ShiprocketAPIError, match="separate explicit"):
        await service.cancel_unbooked_order({"id": 8, "status": "NEW", "shipments": [{"awb": "AWB1"}]})


@pytest.mark.anyio
async def test_delhivery_cleanup_cancels_only_unbooked_and_failure_is_non_destructive(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def find(_self, _id): return {"id": 9, "status": "NEW", "shipments": []}
    async def cancel(_self, _order): return {}
    monkeypatch.setattr(couriers.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(couriers.ShiprocketService, "cancel_unbooked_order", cancel)
    result = await couriers._cleanup_unused_shiprocket_order("1", "323160")
    assert result["status"] == "cancelled" and result["cancel_on_channel"] is False
    async def fail(_self, _order): raise ShiprocketAPIError("provider unavailable")
    monkeypatch.setattr(couriers.ShiprocketService, "cancel_unbooked_order", fail)
    failed = await couriers._cleanup_unused_shiprocket_order("1", "323160")
    assert failed["status"] == "failed"
    assert OrderOperationsStore.get("1")["timeline_events"][-1]["details"]["status"] == "failed"


@pytest.mark.anyio
async def test_cancellation_preflight_protects_local_awb(db, monkeypatch):
    db.add(ShiprocketShipment(order_id="1", provider="shiprocket", awb="AWB", booking_status="booked"))
    db.commit()
    async def context(_self, _id): return {"exists": True, "cancelled": False, "fulfillment_status": "UNFULFILLED"}
    async def find(_self, _id): return None
    monkeypatch.setattr(orders.ShopifyService, "get_order_cancellation_context", context)
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    result = await orders._cancellation_preflight("1", db)
    assert result["allowed"] is False


@pytest.mark.anyio
async def test_shiprocket_cleanup_pending_classifies_cancelled_and_delhivery(db, monkeypatch):
    cancelled = ShopifyService._to_order({**raw_order(), "id": 1, "name": "#1", "order_number": 1, "cancelled_at": "2026-07-25T00:00:00Z"}).model_copy(update={"order_id": "gid1", "order_number": "1", "operational_status": "Cancelled"})
    delhivery = ShopifyService._to_order({**raw_order("paid", "0"), "id": 2, "name": "#2", "order_number": 2, "fulfillment_status": "fulfilled", "fulfillments": [{"status": "success", "tracking_company": "Delhivery", "tracking_number": "D1"}]}).model_copy(update={"order_id": "gid2", "order_number": "2", "operational_status": "Shipped"})
    async def load(_db): return [cancelled, delhivery]
    async def new(_self): return [{"id": 11, "channel_order_id": "1", "status": "NEW", "shipments": []}, {"id": 12, "channel_order_id": "2", "status": "NEW", "shipments": []}]
    monkeypatch.setattr(orders, "_load_orders", load)
    monkeypatch.setattr(orders.ShiprocketService, "list_new_orders", new)
    result = await orders.shiprocket_cleanup_pending(db)
    assert result["total"] == 2
    assert {item["reason"] for item in result["items"]} == {"Cancelled in Shopify", "Direct Delhivery shipment"}
    assert all(item["shiprocket_awb"] is None for item in result["items"])
