"""Regression tests for the 2026-07-21 shipment-state fix (order 322726 class of bug):
locally-derived operational states (call logs, address verification) must never override or
downgrade an order that already has an existing shipment/fulfilment, whether booked through
Mumchies OS or externally via Shopify. Order 322726 itself is used only for manual verification,
not as a hard-coded test case - all fixtures here are synthetic."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import couriers as couriers_module
from app.api.routes.couriers import BookingPayload, shiprocket_book_shipment
from app.api.routes.orders import _merged_operational_state, list_orders
from app.db.base import Base
from app.repositories.shiprocket import upsert_shipment
from app.schemas.orders import OrderProduct, ShippingAddress, ShopifyOrder
from app.services.shiprocket import ShiprocketService
from app.services.shopify import ShopifyService
from app.services.shipment_status import derive_operational_status, has_existing_shipment_evidence


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'shipment_status.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def order(**overrides) -> SimpleNamespace:
    defaults = dict(
        order_id="322726", order_number="322726", cancelled_at=None, shopify_status=None,
        fulfillment_status=None, tags=[], payment_status="paid", shipping_address={"pincode": "411001"},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def confirmed_call_ops(**overrides) -> dict:
    base = {
        "call_logs": [{"result": "Confirmed"}],
        "address_verified": True,
        "package_details": {"weight_kg": 0.95, "length_cm": 5, "breadth_cm": 5, "height_cm": 5},
        "corrected_address": {"pincode": "411001", "address_line1": "Line 1", "city": "Pune", "state": "MH", "customer_name": "Cust", "phone": "9999999999"},
    }
    base.update(overrides)
    return base


# 1. Externally shipped Shopify order is not bookable.
def test_externally_shipped_order_is_not_eligible():
    service = ShiprocketService(email="a@b.com", password="x", pickup_location="Mumchies Factory")
    shipped_order = order(fulfillment_status="fulfilled")
    result = service.evaluate_booking_eligibility(shipped_order, confirmed_call_ops(), shipment=None)
    assert result.eligible is False
    assert any("shipment or fulfilment already exists" in item for item in result.missing_requirements)


# 2. Existing AWB (local shipment) prevents courier eligibility.
def test_existing_local_awb_prevents_eligibility():
    service = ShiprocketService(email="a@b.com", password="x", pickup_location="Mumchies Factory")
    result = service.evaluate_booking_eligibility(order(), confirmed_call_ops(), shipment={"awb": "AWB123", "provider": "shiprocket"})
    assert result.eligible is False
    assert any("shipment or fulfilment already exists" in item for item in result.missing_requirements)


# 3. COD call-log update (Confirmed) does not downgrade Shipped to Ready for Booking.
def test_confirmed_call_log_does_not_downgrade_shipped_status():
    shipped_order = order(fulfillment_status="fulfilled", payment_status="pending")
    status = derive_operational_status(shipped_order, confirmed_call_ops(), shipment=None)
    assert status == "Shipped"


# 4. Multiple call-log updates in sequence do not change shipment state.
def test_multiple_call_logs_never_change_shipped_status():
    shipped_order = order(fulfillment_status="fulfilled", payment_status="pending")
    for logs in (
        [{"result": "Confirmed"}],
        [{"result": "No Answer"}, {"result": "Confirmed"}],
        [{"result": "Confirmed"}, {"result": "No Answer"}, {"result": "Confirmed"}],
    ):
        status = derive_operational_status(shipped_order, {"call_logs": logs}, shipment=None)
        assert status == "Shipped"


# 5. Address correction (address_verified True) does not re-enable booking for a shipped order.
def test_address_verification_does_not_reenable_booking_for_shipped_order():
    service = ShiprocketService(email="a@b.com", password="x", pickup_location="Mumchies Factory")
    shipped_order = order(fulfillment_status="fulfilled", payment_status="paid")
    result = service.evaluate_booking_eligibility(shipped_order, confirmed_call_ops(address_verified=True), shipment=None)
    assert result.eligible is False
    assert result.operational_status == "Shipped"


# 6. Refresh/merge (the real order-list endpoint) preserves shipment status through call logs.
@pytest.mark.anyio
async def test_list_orders_merge_preserves_shipped_status_despite_call_logs(monkeypatch: pytest.MonkeyPatch):
    sample_order = ShopifyOrder(
        order_id="322726", order_number="322726", shopify_name="322726",
        created_date="2026-07-15T10:00:00+05:30", cancelled_at=None, shopify_status=None,
        customer_name="Test Customer", phone="9999999999", email=None,
        shipping_address=ShippingAddress(name="Test Customer", address="Line 1", landmark=None, city="Pune", state="Maharashtra", pincode="411001"),
        customer_id="1", customer_orders_count=1,
        products=[OrderProduct(product_name="Item", sku=None, quantity=1, weight_grams=None, price=100)],
        total_amount=100, payment_status="paid", fulfillment_status="fulfilled", tags=[],
    )

    async def fake_get_latest_orders(self, **_kwargs):
        return [sample_order]

    monkeypatch.setattr("app.api.routes.orders.ShopifyService.get_latest_orders", fake_get_latest_orders)
    monkeypatch.setattr("app.api.routes.orders.get_shipments_by_order_id", lambda _db: {})
    monkeypatch.setattr(
        "app.api.routes.orders.OrderOperationsStore.all",
        lambda: {"322726": {
            "call_logs": [
                {"result": "Confirmed", "timestamp": "2026-07-21T10:00:00", "operator": "Amit", "comment": ""},
                {"result": "No Answer", "timestamp": "2026-07-21T09:00:00", "operator": "Amit", "comment": ""},
                {"result": "Confirmed", "timestamp": "2026-07-21T08:00:00", "operator": "Amit", "comment": ""},
            ],
            "corrected_address": {"customer_name": "Test Customer", "phone": "9999999999", "address_line1": "Line 1", "address_line2": None, "landmark": None, "city": "Pune", "state": "Maharashtra", "pincode": "411001"},
        }},
    )

    orders = await list_orders()
    assert orders[0].operational_status == "Shipped"


# 7. Backend booking endpoint rejects an already-shipped order.
@pytest.mark.anyio
async def test_booking_endpoint_rejects_externally_shipped_order(monkeypatch: pytest.MonkeyPatch, db):
    shipped_order = ShopifyOrder(
        order_id="322726", order_number="322726", shopify_name="322726",
        created_date="2026-07-15T10:00:00+05:30", cancelled_at=None, shopify_status=None,
        customer_name="Test Customer", phone="9999999999", email=None,
        shipping_address=ShippingAddress(name="Test Customer", address="Line 1", landmark=None, city="Pune", state="Maharashtra", pincode="411001"),
        customer_id="1", customer_orders_count=1,
        products=[OrderProduct(product_name="Item", sku=None, quantity=1, weight_grams=None, price=100)],
        total_amount=100, payment_status="paid", fulfillment_status="fulfilled", tags=[],
    )

    async def fake_load_order(_order_id):
        return shipped_order

    monkeypatch.setattr(couriers_module, "_load_order", fake_load_order)
    monkeypatch.setattr(
        "app.services.order_operations.OrderOperationsStore.get",
        lambda _order_id: {"address_verified": True, "call_logs": [{"result": "Confirmed"}], "selected_courier": {"courier_id": "c1", "provider": "shiprocket"}},
    )

    payload = BookingPayload(weight_kg=0.5, courier_id="c1")
    with pytest.raises(HTTPException) as excinfo:
        await shiprocket_book_shipment("322726", payload, db)
    assert excinfo.value.status_code == 409
    assert "already exists" in str(excinfo.value.detail)


# 8. Tracking number/provider/URL are returned for an external shipment.
def test_external_tracking_extracted_from_shopify_fulfillments():
    raw_order = {
        "id": 322726, "name": "#322726", "order_number": 322726, "created_at": "2026-07-15T10:00:00+05:30",
        "customer": {}, "shipping_address": {}, "line_items": [], "shipping_lines": [],
        "total_price": "100.00", "current_total_price": "100.00", "total_outstanding": "0.00",
        "financial_status": "paid", "fulfillment_status": "fulfilled", "cancelled_at": None, "tags": "",
        "payment_gateway_names": [],
        "fulfillments": [
            {"tracking_company": "Delhivery", "tracking_number": "1234567890", "status": "success", "shipment_status": "in_transit", "updated_at": "2026-07-20T10:00:00Z", "tracking_url": None},
        ],
    }
    parsed = ShopifyService._to_order(raw_order)
    assert parsed.external_tracking is not None
    assert parsed.external_tracking.provider == "Delhivery"
    assert parsed.external_tracking.awb == "1234567890"
    assert parsed.external_tracking.status == "in_transit"
    # No URL was supplied by Shopify, but Delhivery is a known/confident provider template.
    assert parsed.external_tracking.tracking_url == "https://www.delhivery.com/track/package/1234567890"


def test_external_tracking_unknown_provider_has_no_invented_url():
    raw_order = {
        "id": 1, "name": "#1", "order_number": 1, "created_at": "2026-07-15T10:00:00+05:30",
        "customer": {}, "shipping_address": {}, "line_items": [], "shipping_lines": [],
        "total_price": "100.00", "current_total_price": "100.00", "total_outstanding": "0.00",
        "financial_status": "paid", "fulfillment_status": "fulfilled", "cancelled_at": None, "tags": "",
        "payment_gateway_names": [],
        "fulfillments": [{"tracking_company": "SomeRegionalCourier", "tracking_number": "XYZ999", "status": "success", "updated_at": "2026-07-20T10:00:00Z", "tracking_url": None}],
    }
    parsed = ShopifyService._to_order(raw_order)
    assert parsed.external_tracking.provider == "SomeRegionalCourier"
    assert parsed.external_tracking.awb == "XYZ999"
    assert parsed.external_tracking.tracking_url is None


def test_no_fulfillments_means_no_external_tracking():
    raw_order = {
        "id": 1, "name": "#1", "order_number": 1, "created_at": "2026-07-15T10:00:00+05:30",
        "customer": {}, "shipping_address": {}, "line_items": [], "shipping_lines": [],
        "total_price": "100.00", "current_total_price": "100.00", "total_outstanding": "0.00",
        "financial_status": "paid", "fulfillment_status": None, "cancelled_at": None, "tags": "",
        "payment_gateway_names": [],
    }
    parsed = ShopifyService._to_order(raw_order)
    assert parsed.external_tracking is None


# 10. Unshipped order remains bookable normally (no regression from the new guard).
def test_unshipped_confirmed_cod_order_remains_eligible():
    service = ShiprocketService(email="a@b.com", password="x", pickup_location="Mumchies Factory")
    plain_order = order(fulfillment_status=None, payment_status="pending")
    result = service.evaluate_booking_eligibility(plain_order, confirmed_call_ops(), shipment=None)
    assert result.eligible is True
    assert result.operational_status == "Ready for Booking"


# 11. Locally booked Shiprocket/Delhivery orders remain unaffected (status shows "Booked" and
# stays "Booked" through subsequent call logs; eligibility blocks re-booking either way).
@pytest.mark.parametrize("provider", ["shiprocket", "delhivery"])
def test_locally_booked_order_status_and_eligibility_unaffected_by_call_logs(provider):
    local_shipment = {"awb": "AWB1", "provider": provider, "booking_status": "booked"}
    booked_order = order(fulfillment_status=None, payment_status="pending")
    status = derive_operational_status(booked_order, confirmed_call_ops(), local_shipment)
    assert status == "Booked"
    service = ShiprocketService(email="a@b.com", password="x", pickup_location="Mumchies Factory")
    result = service.evaluate_booking_eligibility(booked_order, confirmed_call_ops(), local_shipment)
    assert result.eligible is False
    assert result.shipment_exists is True


# 12. Delivered/cancelled edge cases use existing business rules and never allow duplicate booking.
def test_delivered_order_is_not_eligible_and_has_shipment_evidence():
    delivered_order = order(fulfillment_status="delivered", payment_status="pending")
    assert derive_operational_status(delivered_order, confirmed_call_ops(), None) == "Delivered"
    assert has_existing_shipment_evidence(delivered_order, confirmed_call_ops(), None) is True
    service = ShiprocketService(email="a@b.com", password="x", pickup_location="Mumchies Factory")
    result = service.evaluate_booking_eligibility(delivered_order, confirmed_call_ops(), None)
    assert result.eligible is False


def test_cancelled_order_is_not_eligible():
    cancelled_order = order(cancelled_at="2026-07-20T10:00:00Z", payment_status="pending")
    assert derive_operational_status(cancelled_order, confirmed_call_ops(), None) == "Cancelled"
    service = ShiprocketService(email="a@b.com", password="x", pickup_location="Mumchies Factory")
    result = service.evaluate_booking_eligibility(cancelled_order, confirmed_call_ops(), None)
    assert result.eligible is False
