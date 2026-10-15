from pathlib import Path
from types import SimpleNamespace
import pytest

from app.api.routes import shadowfax
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

    with pytest.raises(Exception) as error:
        await shadowfax.shadowfax_create_only_diagnostic(order.order_id, admin_request())
    assert getattr(error.value, "status_code", None) == 410
    assert getattr(error.value, "detail", None) == "The legacy Shadowfax create diagnostic is retired. Direct booking remains feature-disabled pending end-to-end validation."
    assert calls == []


@pytest.mark.anyio
async def test_create_only_diagnostic_is_blocked_even_when_package_data_exists(monkeypatch):
    raw = raw_order(status="paid", outstanding="0")
    raw["shipping_address"].update({"phone": "9999999999", "zip": "560076"})
    raw["payment_gateway_names"] = ["Razorpay"]
    order = ShopifyService._to_order(raw)

    async def load_context(_order_id, _db):
        return order, {"package_details": {"weight_kg": 0.5, "length_cm": 10, "breadth_cm": 8, "height_cm": 6}}, None

    with pytest.raises(Exception) as error:
        await shadowfax.shadowfax_create_only_diagnostic(order.order_id, admin_request())

    assert getattr(error.value, "status_code", None) == 410
    assert getattr(error.value, "detail", None) == "The legacy Shadowfax create diagnostic is retired. Direct booking remains feature-disabled pending end-to-end validation."
def test_direct_shadowfax_booking_has_no_single_order_allowlist() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes" / "couriers.py").read_text(encoding="utf-8")
    assert "SHADOWFAX_CONTROLLED_BOOKING_ORDER_NUMBER" not in source
    assert "_controlled_shadowfax_order_matches" not in source


def test_shadowfax_booking_code_does_not_use_portal_channel_endpoints() -> None:
    root = Path(__file__).resolve().parents[1]
    production_sources = (
        root / "app" / "api" / "routes" / "couriers.py",
        root / "app" / "api" / "routes" / "shadowfax.py",
        root / "app" / "services" / "shadowfax_diagnostics.py",
        root / "app" / "services" / "courier_platform" / "shadowfax_http.py",
    )
    forbidden = ("/api/v2/shopify/orders/", "/api/channel/orders/create/", "/api/shopify/orders/awb/")
    source = "\n".join(path.read_text(encoding="utf-8") for path in production_sources)
    assert not any(endpoint in source for endpoint in forbidden)
