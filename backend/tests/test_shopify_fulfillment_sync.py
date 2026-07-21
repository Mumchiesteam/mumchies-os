from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.orders import router as orders_router
from app.db.base import Base
from app.repositories.shiprocket import get_shipment, upsert_shipment
from app.services.shopify import ShopifySyncError
from app.services.shopify_fulfillment import ShopifyFulfillmentSynchronizer, ShopifyFulfillmentSyncError


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'fulfillment.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def booked(db, order_id="1"):
    return upsert_shipment(
        db, order_id, provider="delhivery", awb="AWB-1", courier_name="Delhivery Surface",
        tracking_url="https://track.example/AWB-1", booking_status="booked",
    )


def fulfillment_order(identifier="fo-1", *, location="loc-1", supported=True, remaining=1):
    return {
        "id": identifier, "status": "OPEN",
        "assignedLocation": {"location": {"id": location, "name": location}},
        "supportedActions": [{"action": "CREATE_FULFILLMENT"}] if supported else [],
        "lineItems": {"nodes": [{"id": f"line-{identifier}", "remainingQuantity": remaining, "totalQuantity": 1}]},
    }


def context(*, orders=None, fulfillments=None, cancelled=False, display="UNFULFILLED"):
    return {
        "id": "gid://shopify/Order/1", "cancelledAt": "2026-01-01" if cancelled else None,
        "displayFulfillmentStatus": display,
        "fulfillmentOrders": {"nodes": orders or []}, "fulfillments": fulfillments or [],
    }


class FakeShopify:
    def __init__(self, order_context, *, scopes=None, fail_create=False, user_error=False):
        self.order_context = order_context
        self.scopes = scopes if scopes is not None else {
            "read_merchant_managed_fulfillment_orders", "write_merchant_managed_fulfillment_orders"
        }
        self.fail_create = fail_create
        self.user_error = user_error
        self.create_calls = []
        self.update_calls = []

    async def granted_access_scopes(self):
        return self.scopes

    async def get_order_fulfillment_context(self, _order_gid):
        return self.order_context

    async def create_fulfillment(self, payload):
        self.create_calls.append(payload)
        if self.fail_create:
            raise ShopifySyncError("Provider operation failed safely.")
        if self.user_error:
            raise ShopifySyncError("Invalid fulfillment line.", user_errors=[{"field": ["lineItems"], "message": "Invalid fulfillment line."}])
        return {"id": f"fulfillment-{len(self.create_calls)}", "status": "SUCCESS"}

    async def update_fulfillment_tracking(self, fulfillment_id, tracking, *, notify_customer):
        self.update_calls.append({"id": fulfillment_id, "tracking": tracking, "notify": notify_customer})
        return {"id": fulfillment_id, "status": "SUCCESS"}


@pytest.mark.anyio
async def test_missing_scopes_fails_safely_and_keeps_booking(db):
    booked(db)
    fake = FakeShopify(context(orders=[fulfillment_order()]), scopes={"read_orders"})
    with pytest.raises(ShopifyFulfillmentSyncError, match="Missing app scopes"):
        await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    shipment = get_shipment(db, "1")
    assert shipment.awb == "AWB-1"
    assert shipment.shopify_fulfillment_sync_status == "failed"


@pytest.mark.anyio
async def test_single_open_fulfillment_order_is_created(db):
    booked(db)
    fake = FakeShopify(context(orders=[fulfillment_order()]))
    result = await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    assert result["shopify_fulfillment_sync_status"] == "synced"
    assert result["shopify_fulfillment_id"] == "fulfillment-1"
    assert fake.create_calls[0]["lineItemsByFulfillmentOrder"][0]["fulfillmentOrderId"] == "fo-1"


@pytest.mark.anyio
async def test_partial_fulfillment_uses_only_remaining_lines(db):
    booked(db)
    fake = FakeShopify(context(orders=[fulfillment_order(remaining=2)]))
    await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    line = fake.create_calls[0]["lineItemsByFulfillmentOrder"][0]["fulfillmentOrderLineItems"][0]
    assert line["quantity"] == 2


@pytest.mark.anyio
async def test_multiple_fulfillment_orders_are_grouped_by_location(db):
    booked(db)
    fake = FakeShopify(context(orders=[
        fulfillment_order("fo-1", location="a"), fulfillment_order("fo-2", location="b")
    ]))
    result = await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    assert len(fake.create_calls) == 2
    assert result["shopify_fulfillment_id"] == "fulfillment-1,fulfillment-2"


@pytest.mark.anyio
async def test_same_awb_is_idempotent(db):
    booked(db)
    existing = {"id": "existing-1", "trackingInfo": [{"number": "AWB-1", "url": "https://old"}]}
    fake = FakeShopify(context(fulfillments=[existing]))
    result = await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    assert result["shopify_fulfillment_id"] == "existing-1"
    assert not fake.create_calls and not fake.update_calls


@pytest.mark.anyio
async def test_fully_fulfilled_single_fulfillment_repairs_tracking(db):
    booked(db)
    fake = FakeShopify(context(fulfillments=[{"id": "existing-1", "trackingInfo": []}], display="FULFILLED"))
    result = await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    assert result["shopify_fulfillment_sync_status"] == "synced"
    assert fake.update_calls[0]["id"] == "existing-1"


@pytest.mark.anyio
async def test_fully_fulfilled_multiple_fulfillments_are_not_overwritten(db):
    booked(db)
    fake = FakeShopify(context(fulfillments=[
        {"id": "one", "trackingInfo": []}, {"id": "two", "trackingInfo": []}
    ], display="FULFILLED"))
    result = await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    assert result["shopify_fulfillment_sync_status"] == "not_applicable"
    assert not fake.update_calls


@pytest.mark.anyio
async def test_cancelled_order_is_not_applicable(db):
    booked(db)
    result = await ShopifyFulfillmentSynchronizer(FakeShopify(context(cancelled=True))).sync(db, "1")
    assert result["shopify_fulfillment_sync_status"] == "not_applicable"


@pytest.mark.anyio
async def test_unsupported_third_party_fulfillment_order_is_skipped(db):
    booked(db)
    fake = FakeShopify(context(orders=[fulfillment_order(supported=False)]))
    result = await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    assert result["shopify_fulfillment_sync_status"] == "not_applicable"
    assert not fake.create_calls


@pytest.mark.anyio
async def test_shopify_failure_does_not_rollback_courier_booking(db):
    booked(db)
    fake = FakeShopify(context(orders=[fulfillment_order()]), fail_create=True)
    with pytest.raises(ShopifyFulfillmentSyncError):
        await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    shipment = get_shipment(db, "1")
    assert shipment.awb == "AWB-1" and shipment.booking_status == "booked"
    assert shipment.shopify_fulfillment_sync_status == "failed"


@pytest.mark.anyio
async def test_customer_notification_is_sent_at_most_once_across_locations(db):
    booked(db)
    fake = FakeShopify(context(orders=[
        fulfillment_order("one", location="a"), fulfillment_order("two", location="b")
    ]))
    await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    notifications = [call["notifyCustomer"] for call in fake.create_calls]
    assert notifications == [True, False]
    assert get_shipment(db, "1").shopify_customer_notified is True


@pytest.mark.anyio
async def test_manual_retry_can_recover_a_failed_sync(db):
    booked(db)
    failing = FakeShopify(context(orders=[fulfillment_order()]), fail_create=True)
    with pytest.raises(ShopifyFulfillmentSyncError):
        await ShopifyFulfillmentSynchronizer(failing).sync(db, "1")
    recovered = await ShopifyFulfillmentSynchronizer(FakeShopify(context(orders=[fulfillment_order()]))).sync(db, "1")
    assert recovered["shopify_fulfillment_sync_status"] == "synced"


def test_manual_sync_route_is_registered():
    assert any(getattr(route, "path", None) == "/orders/{order_id}/shopify-fulfillment/sync" for route in orders_router.routes)


@pytest.mark.anyio
async def test_graphql_user_error_persists_failed_state(db):
    booked(db)
    fake = FakeShopify(context(orders=[fulfillment_order()]), user_error=True)
    with pytest.raises(ShopifyFulfillmentSyncError, match="Invalid fulfillment line"):
        await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    assert get_shipment(db, "1").shopify_fulfillment_sync_status == "failed"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider", "courier_name", "expected_company"),
    [("delhivery", "Delhivery Surface", "Delhivery"), ("shiprocket", "Xpressbees Surface", "Xpressbees Surface")],
)
async def test_provider_tracking_company_mapping(db, provider, courier_name, expected_company):
    upsert_shipment(
        db, "1", provider=provider, awb="AWB-1", courier_name=courier_name,
        tracking_url="https://track.example/AWB-1", booking_status="booked",
    )
    fake = FakeShopify(context(orders=[fulfillment_order()]))
    await ShopifyFulfillmentSynchronizer(fake).sync(db, "1")
    assert fake.create_calls[0]["trackingInfo"]["company"] == expected_company
