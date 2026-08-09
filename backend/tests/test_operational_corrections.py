from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import couriers, orders
from app.api.routes.couriers import ManualShadowfaxPayload
from app.api.routes.orders import AddressConfirmationPayload, CancellationPayload, SaveVerifyAddressPayload, ShiprocketOnlyCancellationPayload
from app.models.shiprocket import ShiprocketShipment
from app.models.user import User
from app.db.base import Base
from app.services import order_operations
from app.services.order_operations import OrderOperationsStore
from app.services.shiprocket import ShiprocketAPIError, ShiprocketService
from app.services.shopify import ShopifySyncError
from app.services.shopify import ShopifyService
from app.services.temporary_shadowfax_repair import repair_legacy_shadowfax_test_324541
from tests.test_operations_upgrade import raw_order


def authenticated_request(display_name="Authenticated Operator"):
    return SimpleNamespace(state=SimpleNamespace(auth_user=User(username="operator", display_name=display_name, password_hash="unused", role="operator", is_active=True)))


def admin_request(role="admin"):
    return SimpleNamespace(state=SimpleNamespace(auth_user=User(username=role, display_name=role.title(), password_hash="unused", role=role, is_active=True)))


@pytest.mark.anyio
async def test_shadowfax_shipment_row_diagnostic_is_read_only_and_reports_exact_blocker(db):
    shipment = ShiprocketShipment(
        order_id="6854925713486", provider="shadowfax", provider_order_id=None,
        shipment_id="stale-id", awb=None, booking_status="booking_failed",
        latest_status="Booking failed", courier_name="Stored courier", courier_service="Stored service",
        raw_provider_response='{"token":"secret","status":"rejected"}',
    )
    db.add(shipment)
    db.commit()

    result = await couriers.temporary_shadowfax_direct_test_324541_shipment_row(admin_request(), db)

    assert result["fields"]["shipment_id"] == "stale-id"
    assert result["fields"]["raw_provider_response"] == {"token": "[REDACTED]", "status": "rejected"}
    assert result["non_null"]["shipment_id"] is True
    assert result["non_null"]["awb"] is False
    assert result["reset_blocker"] == {
        "evaluates_true": True,
        "condition": "provider == shadowfax AND (genuine provider_order_id OR shipment_id OR awb OR booked_at OR booking_status in [booked, manual_confirmed])",
        "true_fields": ["shipment_id"],
    }
    assert db.get(ShiprocketShipment, "6854925713486").shipment_id == "stale-id"


@pytest.mark.anyio
async def test_shadowfax_shipment_row_diagnostic_requires_admin(db):
    with pytest.raises(Exception) as error:
        await couriers.temporary_shadowfax_direct_test_324541_shipment_row(authenticated_request(), db)
    assert getattr(error.value, "status_code", None) == 403


def test_shadowfax_direct_diagnostics_merge_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    OrderOperationsStore.update_shadowfax_direct_test("1", create_request_started_at="2026-08-09T00:00:00+00:00", create_result="unknown")
    state = OrderOperationsStore.update_shadowfax_direct_test("1", create_http_status=422, create_result="provider_rejected")
    assert state == {
        "create_request_started_at": "2026-08-09T00:00:00+00:00",
        "create_result": "provider_rejected", "create_http_status": 422,
    }
    assert "token" not in str(OrderOperationsStore.get("1").get("shadowfax_direct_test")).casefold()


def test_legacy_shadowfax_reset_removes_only_temporary_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    OrderOperationsStore.record_timeline_event("1", "address_verified", operator="Owner")
    OrderOperationsStore.record_timeline_event("1", "shadowfax_direct_test_324541_started", operator="Owner")
    OrderOperationsStore.update_shadowfax_direct_test("1", final_test_state="legacy_attempt_observed_without_diagnostics")
    OrderOperationsStore.reset_legacy_shadowfax_direct_test("1")
    record = OrderOperationsStore.get("1")
    assert record["shadowfax_direct_test"] is None
    assert [event["action"] for event in record["timeline_events"]] == ["address_verified"]


def test_exact_324541_stale_identifier_repair_and_test_reset(db, tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    shipment = ShiprocketShipment(
        order_id="6854925713486", provider="shadowfax", provider_order_id="324541",
        shipment_id=None, awb=None, booking_status="booking_failed", booked_at=None,
        latest_status="Booking failed",
    )
    db.add(shipment)
    db.commit()
    OrderOperationsStore.record_timeline_event(
        shipment.order_id, "shadowfax_direct_test_324541_started", operator="Owner",
    )

    result = repair_legacy_shadowfax_test_324541(db)

    assert result == {"provider_order_id_cleared": True, "test_state_reset": True}
    db.refresh(shipment)
    assert shipment.provider_order_id is None
    assert shipment.provider == "shadowfax" and shipment.booking_status == "booking_failed"
    assert shipment.shipment_id is None and shipment.awb is None and shipment.booked_at is None
    operations = OrderOperationsStore.get(shipment.order_id)
    assert operations["shadowfax_direct_test"] is None
    assert not any(event["action"] == "shadowfax_direct_test_324541_started" for event in operations["timeline_events"])


def test_324541_repair_refuses_any_genuine_identifier(db, tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    shipment = ShiprocketShipment(
        order_id="6854925713486", provider="shadowfax", provider_order_id="324541",
        shipment_id="shadowfax-id", awb=None, booking_status="booking_failed", booked_at=None,
    )
    db.add(shipment)
    db.commit()
    OrderOperationsStore.record_timeline_event(
        shipment.order_id, "shadowfax_direct_test_324541_started", operator="Owner",
    )

    result = repair_legacy_shadowfax_test_324541(db)

    assert result == {"provider_order_id_cleared": False, "test_state_reset": False}
    assert db.get(ShiprocketShipment, shipment.order_id).provider_order_id == "324541"


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
    record = await orders.add_address_confirmation_comment("1", AddressConfirmationPayload(comment="Gate confirmed", operator="Untrusted"), authenticated_request())
    entry = record["address_confirmation_comments"][0]
    assert entry["comment"] == "Gate confirmed" and entry["operator"] == "Authenticated Operator"
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
    result = await orders.save_and_verify_address("1", payload, authenticated_request(), db)
    assert result["verified"] is True and result["operations"]["address_verified_by"] == "Authenticated Operator"
    assert calls == ["order", ("customer", False)]
    OrderOperationsStore.save_address("1", {"address_line1": "Changed"}, operator="Operator")
    assert OrderOperationsStore.get("1")["address_verified"] is False


def preflight(*, shopify=True, shiprocket=True):
    return {"allowed": True, "shopify": {"exists": shopify}, "shiprocket": {"exists": shiprocket, "status": "NEW", "lookup_id": "322835"}, "shipment": {"exists": False}, "blocked_reason": None}


@pytest.mark.anyio
async def test_local_only_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def pf(_id, _db): return preflight(shopify=False, shiprocket=False)
    monkeypatch.setattr(orders, "_cancellation_preflight", pf)
    result = await orders.cancel_order("1", CancellationPayload(operator="Untrusted"), authenticated_request(), None)
    assert result["results"]["mumchies_os"]["status"] == "cancelled"
    assert result["results"]["shopify"]["status"] == "not_applicable"


@pytest.mark.anyio
async def test_shopify_and_shiprocket_cancellation_are_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def pf(_id, _db): return preflight()
    async def shopify_cancel(_self, _id): return {"status": "cancelled"}
    async def find(_self, _id): return {"id": 99, "status": "NEW", "shipments": []}
    async def shiprocket_cancel(_self, _order): return {"classification": "accepted"}
    monkeypatch.setattr(orders, "_cancellation_preflight", pf)
    monkeypatch.setattr(orders.ShopifyService, "cancel_order", shopify_cancel)
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(orders.ShiprocketService, "cancel_unbooked_order", shiprocket_cancel)
    result = await orders.cancel_order("1", CancellationPayload(operator="Untrusted"), authenticated_request(), None)
    assert result["results"]["shopify"]["status"] == "cancelled"
    assert result["results"]["shiprocket"] == {"status": "cancelled", "cancel_on_channel": False}


@pytest.mark.anyio
async def test_cancellation_looks_up_shiprocket_by_shopify_order_number(db, monkeypatch):
    seen = []
    async def context(_self, _id): return {"exists": True, "cancelled": False, "fulfillment_status": "UNFULFILLED", "order_number": "322835"}
    async def find(_self, lookup_id):
        seen.append(lookup_id)
        return {"id": 99, "channel_order_id": "322835", "status": "NEW", "shipments": []}
    monkeypatch.setattr(orders.ShopifyService, "get_order_cancellation_context", context)
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    result = await orders._cancellation_preflight("6813934747726", db)
    assert seen == ["322835"]
    assert result["shiprocket"]["exists"] is True
    assert result["shiprocket"]["lookup_id"] == "322835"


@pytest.mark.anyio
async def test_already_cancelled_shiprocket_order_is_not_cancelled_again(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def pf(_id, _db):
        value = preflight()
        value["shiprocket"]["status"] = "CANCELED"
        return value
    async def unexpected(*_args): raise AssertionError("already cancelled order was sent again")
    monkeypatch.setattr(orders, "_cancellation_preflight", pf)
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", unexpected)
    result = await orders.cancel_order("1", CancellationPayload(cancel_shopify=False), authenticated_request(), None)
    assert result["results"]["shiprocket"]["status"] == "Already cancelled"


@pytest.mark.anyio
async def test_shiprocket_application_rejection_is_reported_as_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def pf(_id, _db): return preflight(shopify=False)
    async def find(_self, _id): return {"id": 99, "status": "NEW", "shipments": []}
    async def reject(_self, _order): raise ShiprocketAPIError("Cancellation not allowed")
    monkeypatch.setattr(orders, "_cancellation_preflight", pf)
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(orders.ShiprocketService, "cancel_unbooked_order", reject)
    result = await orders.cancel_order("1", CancellationPayload(), authenticated_request(), None)
    assert result["results"]["shiprocket"] == {"status": "failed", "error": "Cancellation not allowed", "cancel_on_channel": False}


@pytest.mark.anyio
async def test_partial_cancellation_failure_is_reported_and_local_state_survives(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def pf(_id, _db): return preflight(shopify=True, shiprocket=False)
    async def fail(_self, _id): raise ShopifySyncError("denied")
    monkeypatch.setattr(orders, "_cancellation_preflight", pf)
    monkeypatch.setattr(orders.ShopifyService, "cancel_order", fail)
    result = await orders.cancel_order("1", CancellationPayload(operator="Untrusted"), authenticated_request(), None)
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
async def test_shiprocket_cancel_rejects_application_error_on_http_200(monkeypatch):
    service = ShiprocketService()
    async def post(_url, _payload):
        return httpx.Response(200, json={"success": False, "message": "Cancellation not allowed"})
    monkeypatch.setattr(service, "_post", post)
    with pytest.raises(ShiprocketAPIError, match="Cancellation not allowed"):
        await service.cancel_unbooked_order({"id": 7, "status": "NEW", "shipments": []})


@pytest.mark.anyio
@pytest.mark.parametrize("cancelled_at,shopify_status", [
    ("2026-08-08T10:00:00Z", None),
    (None, "cancelled"),
    (None, "canceled"),
])
async def test_cancelled_unfulfilled_order_cannot_create_manual_shadowfax_evidence(monkeypatch, cancelled_at, shopify_status):
    order = SimpleNamespace(cancelled_at=cancelled_at, shopify_status=shopify_status, fulfillment_status="unfulfilled")
    async def context(_order_id, _db): return order, {"selected_courier": {"provider": "shadowfax"}}, None
    monkeypatch.setattr(couriers, "_load_context", context)
    monkeypatch.setattr(couriers, "upsert_shipment", lambda *_args, **_kwargs: pytest.fail("shipment evidence was persisted"))
    with pytest.raises(orders.HTTPException, match="Cancelled Shopify orders") as error:
        await couriers.save_manual_shadowfax_shipment("1", ManualShadowfaxPayload(provider_id="SFX-1"), authenticated_request(), None)
    assert error.value.status_code == 409


@pytest.mark.anyio
async def test_eligible_order_can_create_manual_shadowfax_evidence(monkeypatch):
    order = SimpleNamespace(cancelled_at=None, shopify_status="open", fulfillment_status="unfulfilled", tags=[], payment_status="pending")
    operations = {"selected_courier": {"provider": "shadowfax"}}
    async def context(_order_id, _db): return order, operations, None
    saved = {}
    def persist(_db, order_id, **values): saved.update(order_id=order_id, **values); return saved
    monkeypatch.setattr(couriers, "_load_context", context)
    monkeypatch.setattr(couriers, "get_shipment", lambda *_args: None)
    monkeypatch.setattr(couriers, "upsert_shipment", persist)
    monkeypatch.setattr(couriers, "shipment_snapshot", lambda value: dict(value))
    monkeypatch.setattr(OrderOperationsStore, "record_timeline_event", lambda *_args, **_kwargs: {})
    result = await couriers.save_manual_shadowfax_shipment("1", ManualShadowfaxPayload(provider_id="SFX-1"), authenticated_request(), None)
    assert result["shipment"]["provider"] == "shadowfax"
    assert result["shipment"]["booking_mode"] == "manual"
    assert result["shipment"]["provider_order_id"] == "SFX-1"


@pytest.mark.anyio
async def test_delhivery_cleanup_cancels_only_unbooked_and_failure_is_non_destructive(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def find(_self, _id): return {"id": 9, "status": "NEW", "shipments": []}
    async def cancel(_self, _order): return {}
    monkeypatch.setattr(couriers.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(couriers.ShiprocketService, "cancel_unbooked_order", cancel)
    result = await couriers._cleanup_unused_shiprocket_order("1", "323160", "Authenticated Operator")
    assert result["status"] == "cancelled" and result["cancel_on_channel"] is False
    async def fail(_self, _order): raise ShiprocketAPIError("provider unavailable")
    monkeypatch.setattr(couriers.ShiprocketService, "cancel_unbooked_order", fail)
    failed = await couriers._cleanup_unused_shiprocket_order("1", "323160", "Authenticated Operator")
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


def cleanup_payload():
    return ShiprocketOnlyCancellationPayload(shiprocket_order_id="77", order_number="322835", operator="Operator")


@pytest.mark.anyio
async def test_shiprocket_http_200_success_requires_cancelled_top_level(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    service_order = {"id": 77, "channel_order_id": "322835", "status": "NEW", "shipments": []}
    async def new(_self, force_refresh=False): return [service_order]
    async def request(_self, _order): return {"http_status": 200, "response": {"status_code": 200, "message": "Order cancelled successfully"}, "classification": "accepted"}
    async def find(_self, _number): return {**service_order, "status": "CANCELED", "status_code": 5}
    async def no_sleep(_seconds): return None
    monkeypatch.setattr(orders.ShiprocketService, "list_new_orders", new)
    monkeypatch.setattr(orders.ShiprocketService, "request_unbooked_order_cancellation", request)
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(orders.asyncio, "sleep", no_sleep)
    result = await orders.shiprocket_only_cancel("1", cleanup_payload(), authenticated_request())
    assert result["status"] == "confirmed"
    assert result["verified_top_level_status_code"] == 5


@pytest.mark.anyio
async def test_shiprocket_http_200_application_rejection_is_not_success(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    current = {"id": 77, "channel_order_id": "322835", "status": "NEW", "status_code": 1, "products": [], "activities": []}
    async def find(_self, _number): return current
    async def new(_self, force_refresh=False): return [current]
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(orders.ShiprocketService, "list_new_orders", new)
    request = {"http_status": 200, "response": {"success": False, "message": "Cancellation not allowed"}, "classification": "rejected"}
    result = await orders._verify_shiprocket_only_cancellation("1", cleanup_payload(), operator="Authenticated Operator", request_result=request)
    assert result["status"] == "rejected"


@pytest.mark.anyio
async def test_shiprocket_nested_cancelled_but_top_level_new_is_inconsistent(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    current = {"id": 77, "channel_order_id": "322835", "status": "NEW", "status_code": 1, "products": [{"status": "CANCELED", "status_code": 5}], "activities": ["ORDER_CANCELLED"]}
    async def find(_self, _number): return current
    async def new(_self, force_refresh=False): return [current]
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(orders.ShiprocketService, "list_new_orders", new)
    result = await orders._verify_shiprocket_only_cancellation("1", cleanup_payload(), operator="Authenticated Operator", request_result={"http_status": 200, "response": {}, "classification": "accepted"})
    assert result["status"] == "inconsistent"
    assert result["still_in_new_queue"] is True
    audit = OrderOperationsStore.get("1")["timeline_events"][-1]
    assert audit["details"]["operator"] == "Authenticated Operator"
    assert audit["details"]["timestamp_ist"].endswith(" IST")


@pytest.mark.anyio
async def test_shiprocket_disappearing_from_new_confirms_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    async def find(_self, _number): return {"id": 77, "channel_order_id": "322835", "status": "PROCESSING", "status_code": 18}
    async def new(_self, force_refresh=False): return []
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(orders.ShiprocketService, "list_new_orders", new)
    result = await orders._verify_shiprocket_only_cancellation("1", cleanup_payload(), operator="Authenticated Operator", request_result={"http_status": 200, "response": {}, "classification": "ambiguous"})
    assert result["status"] == "confirmed"
    assert result["still_in_new_queue"] is False


@pytest.mark.anyio
async def test_verification_retry_does_not_resend_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    calls = {"send": 0}
    async def send(_self, _order): calls["send"] += 1; raise AssertionError("verification resent cancellation")
    async def find(_self, _number): return {"id": 77, "channel_order_id": "322835", "status": "NEW", "status_code": 1}
    async def new(_self, force_refresh=False): return [{"id": 77, "channel_order_id": "322835", "status": "NEW"}]
    monkeypatch.setattr(orders.ShiprocketService, "request_unbooked_order_cancellation", send)
    monkeypatch.setattr(orders.ShiprocketService, "find_existing_order", find)
    monkeypatch.setattr(orders.ShiprocketService, "list_new_orders", new)
    result = await orders.verify_shiprocket_only_cancel("1", cleanup_payload(), authenticated_request())
    assert result["status"] == "unverified"
    assert calls["send"] == 0


def test_shiprocket_response_classification_and_secret_sanitizing():
    assert ShiprocketService.classify_cancellation_response({"status_code": 200, "message": "Cancelled successfully"}) == "accepted"
    assert ShiprocketService.classify_cancellation_response({"success": False, "message": "Cancellation not allowed"}) == "rejected"
    assert ShiprocketService.classify_cancellation_response({"message": "Request received"}) == "ambiguous"
    assert ShiprocketService.sanitize_response({"token": "secret", "message": "ok"}) == {"token": "[REDACTED]", "message": "ok"}
