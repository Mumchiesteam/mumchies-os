from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.routes import couriers, shadowfax
from app.api.routes.couriers import _controlled_shadowfax_order_matches
from app.core.config import settings
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
def test_controlled_shadowfax_booking_requires_one_explicit_order(monkeypatch) -> None:
    monkeypatch.setattr(settings, "shadowfax_controlled_booking_order_number", None)
    assert _controlled_shadowfax_order_matches("326900") is False
    monkeypatch.setattr(settings, "shadowfax_controlled_booking_order_number", "#326900")
    assert _controlled_shadowfax_order_matches("326900") is True
    assert _controlled_shadowfax_order_matches("326901") is False


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


@pytest.mark.anyio
async def test_controlled_shadowfax_success_persists_before_shopify_sync(monkeypatch) -> None:
    raw = raw_order(status="paid", outstanding="0")
    raw["shipping_address"].update({"phone": "9999999999", "zip": "560076"})
    order = ShopifyService._to_order(raw)
    selected = {"provider": "shadowfax", "courier_id": "shadowfax:controlled", "courier_name": "Shadowfax"}
    payload = couriers.BookingPayload(
        weight_kg=0.5, length_cm=10, breadth_cm=8, height_cm=6,
        courier_id="shadowfax:controlled", provider="shadowfax", courier_name="Shadowfax",
        draft_order_id=order.order_id, address_revision=0, booking_context_hash="context",
    )
    events: list[str] = []

    async def load_context(_order_id, _db):
        return order, {"selected_courier": selected}, None

    class Eligibility:
        eligible = True
        missing_requirements: list[str] = []

    class Platform:
        async def book(self, *_args, **_kwargs):
            events.append("provider_create_and_persist")
            return {"shipment": {"provider_order_id": "SF-ORDER-1", "awb": "SF123"}, "existing": False}

    async def sync(_db, _order):
        assert events == ["provider_create_and_persist", "mark_sync_pending"]
        events.append("shopify_sync")
        return {"provider_order_id": "SF-ORDER-1", "awb": "SF123"}

    monkeypatch.setattr(settings, "shadowfax_controlled_booking_order_number", order.order_number)
    monkeypatch.setattr(couriers, "_load_context", load_context)
    monkeypatch.setattr(couriers, "has_existing_shipment_evidence", lambda *_args: False)
    monkeypatch.setattr(couriers.ShiprocketService, "evaluate_booking_eligibility", lambda *_args: Eligibility())
    monkeypatch.setattr(couriers, "_booking_selection_matches", lambda *_args: True)
    monkeypatch.setattr(couriers, "_booking_context", lambda *_args: SimpleNamespace(order=order, package=payload, address_revision=0, context_hash="context"))
    monkeypatch.setattr(couriers, "_context_operations", lambda _context: {"selected_courier": selected})
    async def provider_payload(*_args):
        return {"order_type": "warehouse"}

    monkeypatch.setattr(couriers, "_build_provider_booking_request", provider_payload)
    monkeypatch.setattr(couriers, "_validate_shadowfax_booking_request", lambda *_args: None)
    monkeypatch.setattr(couriers, "_assert_booking_payload", lambda *_args: None)
    monkeypatch.setattr(couriers, "CourierPlatformService", Platform)
    monkeypatch.setattr(couriers, "upsert_shipment", lambda *_args, **_kwargs: events.append("mark_sync_pending"))
    monkeypatch.setattr(couriers, "_sync_shopify_after_booking", sync)

    result = await couriers.controlled_shadowfax_booking(order.order_id, payload, admin_request(), None)

    assert result["controlled"] is True
    assert events == ["provider_create_and_persist", "mark_sync_pending", "shopify_sync"]
