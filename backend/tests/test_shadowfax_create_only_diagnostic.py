from types import SimpleNamespace

import pytest

from app.api.routes import couriers, shadowfax
from app.models.user import User
from app.services.shopify import ShopifyService
from tests.test_operations_upgrade import raw_order


def admin_request():
    return SimpleNamespace(
        state=SimpleNamespace(
            auth_user=User(username="admin", display_name="Admin", password_hash="unused", role="admin", is_active=True),
        ),
    )


@pytest.mark.anyio
async def test_create_only_diagnostic_blocks_shopify_orders_before_any_provider_call(monkeypatch):
    raw = raw_order(status="paid", outstanding="0")
    raw["shipping_address"].update({"phone": "9999999999", "zip": "560076"})
    raw["payment_gateway_names"] = ["Razorpay"]
    order = ShopifyService._to_order(raw)
    calls: list[str] = []

    async def load_context(order_id, received_db):
        assert order_id == order.order_id
        assert received_db is None
        return order, {}, None

    class Adapter:
        async def create_booking(self, payload):
            calls.append("shadowfax.create_booking")

    monkeypatch.setattr(shadowfax, "_load_context", load_context)
    monkeypatch.setattr(shadowfax, "ShadowfaxAdapter", Adapter)
    shadowfax._create_only_attempted_order_ids.clear()

    with pytest.raises(Exception) as error:
        await shadowfax.shadowfax_create_only_diagnostic(order.order_id, admin_request(), None)
    assert getattr(error.value, "status_code", None) == 409
    assert getattr(error.value, "detail", None) == "Standalone Shadowfax creation is forbidden for Shopify-origin orders."
    assert calls == []


@pytest.mark.anyio
async def test_create_only_diagnostic_is_blocked_even_when_package_data_exists(monkeypatch):
    raw = raw_order(status="paid", outstanding="0")
    raw["shipping_address"].update({"phone": "9999999999", "zip": "560076"})
    raw["payment_gateway_names"] = ["Razorpay"]
    order = ShopifyService._to_order(raw)

    async def load_context(_order_id, _db):
        return order, {"package_details": {"weight_kg": 0.5, "length_cm": 10, "breadth_cm": 8, "height_cm": 6}}, None

    monkeypatch.setattr(shadowfax, "_load_context", load_context)
    shadowfax._create_only_attempted_order_ids.clear()

    with pytest.raises(Exception) as error:
        await shadowfax.shadowfax_create_only_diagnostic(order.order_id, admin_request(), None)

    assert getattr(error.value, "status_code", None) == 409
    assert getattr(error.value, "detail", None) == "Standalone Shadowfax creation is forbidden for Shopify-origin orders."
