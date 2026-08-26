from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.routes import couriers
from app.api.routes.couriers import CourierCheckPayload
from app.schemas.orders import ShopifyOrder
from app.services.delhivery import DelhiveryQuote
from app.services.shiprocket import CourierQuote


def order() -> ShopifyOrder:
    return ShopifyOrder(
        order_id="1", order_number="325557", created_date=datetime.now(timezone.utc).isoformat(),
        customer_name="Lookup", total_amount=100, order_total=100, payment_type="prepaid", products=[], tags=[],
    )


def eligibility():
    return SimpleNamespace(
        eligible=True, missing_requirements=[], operational_status="Ready for Booking",
        payment_mode="Prepaid", shipment_exists=False, shipment_status=None, shipment_snapshot=None,
    )


@pytest.fixture
def lookup_context(monkeypatch):
    async def load(_order_id, _db):
        return order(), {"address_verified": True}, None

    async def pickup(*_args):
        return "560076", "400001", False

    monkeypatch.setattr(couriers, "_load_context", load)
    monkeypatch.setattr(couriers, "_serviceability_query", pickup)
    monkeypatch.setattr(couriers.OrderOperationsStore, "prepare_courier_lookup", lambda _order_id, package, _actor: {"address_verified": True, "package_details": package, "selected_courier": None})
    monkeypatch.setattr(couriers, "current_actor", lambda _request: "Tester")
    monkeypatch.setattr(couriers.ShiprocketService, "evaluate_booking_eligibility", lambda *_args: eligibility())
    return SimpleNamespace(rollback=lambda: None)


@pytest.mark.anyio
async def test_shiprocket_success_delhivery_failure_returns_shiprocket(monkeypatch, lookup_context):
    async def shiprocket(*_args):
        return [CourierQuote("43", "Shiprocket Surface", 50, None, 50, None, None, None, True, True, "surface")]

    async def delhivery(*_args):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(couriers.ShiprocketService, "serviceability", shiprocket)
    monkeypatch.setattr(couriers.DelhiveryService, "configured", property(lambda _self: True))
    monkeypatch.setattr(couriers.DelhiveryService, "serviceability", delhivery)
    result = await couriers.shiprocket_serviceability("1", CourierCheckPayload(weight_kg=.5, courier_payment_mode="Prepaid"), SimpleNamespace(), lookup_context)
    assert any(quote["provider"] == "shiprocket" for quote in result["couriers"])
    assert result["provider_failures"] == {"delhivery": "unavailable"}
    assert result["lookup_status"] == "partial"


@pytest.mark.anyio
async def test_delhivery_success_shiprocket_failure_returns_delhivery(monkeypatch, lookup_context):
    async def shiprocket(*_args):
        raise RuntimeError("provider unavailable")

    async def delhivery(*_args):
        return [DelhiveryQuote("d1", "Delhivery", 60, None, 60, None, None, None, True, True, "surface")]

    monkeypatch.setattr(couriers.ShiprocketService, "serviceability", shiprocket)
    monkeypatch.setattr(couriers.DelhiveryService, "configured", property(lambda _self: True))
    monkeypatch.setattr(couriers.DelhiveryService, "serviceability", delhivery)
    result = await couriers.shiprocket_serviceability("1", CourierCheckPayload(weight_kg=.5, courier_payment_mode="Prepaid"), SimpleNamespace(), lookup_context)
    assert any(quote["provider"] == "delhivery" for quote in result["couriers"])
    assert result["provider_failures"] == {"shiprocket": "unavailable"}


@pytest.mark.anyio
async def test_provider_timeouts_return_manual_option_and_combined_error(monkeypatch, lookup_context):
    async def timeout(*_args):
        raise asyncio.TimeoutError

    monkeypatch.setattr(couriers.ShiprocketService, "serviceability", timeout)
    monkeypatch.setattr(couriers.DelhiveryService, "configured", property(lambda _self: True))
    monkeypatch.setattr(couriers.DelhiveryService, "serviceability", timeout)
    result = await couriers.shiprocket_serviceability("1", CourierCheckPayload(weight_kg=.5, courier_payment_mode="Prepaid"), SimpleNamespace(), lookup_context)
    assert result["lookup_status"] == "manual_only"
    assert result["provider_failures"] == {"shiprocket": "timeout", "delhivery": "timeout"}
    assert [quote["provider"] for quote in result["couriers"]] == ["shadowfax"]
    assert any("both rate providers" in warning for warning in result["provider_warnings"])


@pytest.mark.anyio
async def test_ineligible_order_can_prefetch_but_response_remains_locked(monkeypatch, lookup_context):
    locked = eligibility()
    locked.eligible = False
    locked.missing_requirements = ["address must be verified"]
    monkeypatch.setattr(couriers.ShiprocketService, "evaluate_booking_eligibility", lambda *_args: locked)
    monkeypatch.setattr(couriers.ShiprocketService, "serviceability", lambda *_args: [])
    monkeypatch.setattr(couriers.DelhiveryService, "configured", property(lambda _self: False))
    payload = CourierCheckPayload(
        weight_kg=.5, courier_payment_mode="Prepaid", drawer_generation=9, client_context_key="drawer-9",
        quote_address={"customer_name": "Lookup", "phone": "9876543210", "address_line1": "Street", "address_line2": "", "landmark": "", "city": "Mumbai", "state": "Maharashtra", "pincode": "400001"},
    )
    result = await couriers.shiprocket_serviceability("1", payload, SimpleNamespace(), lookup_context)
    assert result["booking_readiness"]["eligible"] is False
    assert result["client_context_key"] == "drawer-9"
    assert result["quote_context"]["drawer_generation"] == 9
    assert len(result["quote_context_fingerprint"]) == 64


def test_partial_cod_uses_authoritative_cod_provider_mode():
    partial = order().model_copy(update={"payment_type": "partial_cod"})
    assert couriers._order_payment_mode(partial) == "COD"
