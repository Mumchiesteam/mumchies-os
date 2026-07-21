from __future__ import annotations

import pytest

from app.api.routes.orders import list_orders
from app.schemas.orders import OrderProduct, ShopifyOrder, ShippingAddress


@pytest.mark.anyio
async def test_orders_endpoint_merges_persisted_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    sample_order = ShopifyOrder(
        order_id="1",
        order_number="322232",
        shopify_name="322232",
        created_date="2026-07-17T10:00:00+05:30",
        cancelled_at=None,
        shopify_status=None,
        customer_name="Test Customer",
        phone="9999999999",
        email=None,
        shipping_address=ShippingAddress(name="Test Customer", address="Line 1", landmark=None, city="Pune", state="Maharashtra", pincode="411001"),
        customer_id="42",
        customer_orders_count=1,
        products=[OrderProduct(product_name="Item", sku=None, quantity=1, weight_grams=None, price=100)],
        total_amount=100,
        shipping_amount=0,
        payment_status="paid",
        fulfillment_status=None,
        tags=[],
    )

    async def fake_get_latest_orders(self, **_kwargs):  # noqa: ANN001
        return [sample_order]

    monkeypatch.setattr("app.api.routes.orders.ShopifyService.get_latest_orders", fake_get_latest_orders)
    monkeypatch.setattr("app.api.routes.orders.get_shipments_by_order_id", lambda _db: {})
    monkeypatch.setattr(
        "app.api.routes.orders.OrderOperationsStore.all",
        lambda: {
            "1": {
                "call_logs": [{"result": "Callback Requested", "timestamp": "2026-07-17T11:00:00", "operator": "Amit Kumar", "comment": "Call back"}],
                "corrected_address": {"customer_name": "Test Customer", "phone": "9999999999", "address_line1": "Line 1", "address_line2": None, "landmark": None, "city": "Pune", "state": "Maharashtra", "pincode": "411001"},
                "address_verified": True,
                "address_verified_at": "2026-07-17T11:05:00",
                "address_verified_by": "Amit Kumar",
                "verified_address_snapshot": {"customer_name": "Test Customer", "phone": "9999999999", "address_line1": "Line 1", "address_line2": None, "landmark": None, "city": "Pune", "state": "Maharashtra", "pincode": "411001"},
                "courier_sync_status": "Not synchronized",
                "courier_sync_error": None,
            }
        },
    )

    orders = await list_orders()
    assert orders[0].latest_call_result == "Callback Requested"
    assert orders[0].operational_status == "Ready for Booking"
    assert orders[0].address_verified is True
    assert orders[0].address_verified_by == "Amit Kumar"
