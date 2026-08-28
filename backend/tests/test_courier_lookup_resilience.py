from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.routes import couriers
from app.api.routes.couriers import CourierCheckPayload
from app.schemas.orders import ShopifyOrder
from app.services.delhivery import DelhiveryQuote
from app.services.shiprocket import CourierQuote, ShiprocketService


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


def verified_address(pincode: str = "400001") -> dict[str, str]:
    return {
        "customer_name": "Lookup", "phone": "9876543210", "address_line1": "Street",
        "address_line2": "", "landmark": "", "city": "Mumbai", "state": "Maharashtra",
        "pincode": pincode,
    }


@pytest.fixture
def lookup_context(monkeypatch):
    async def load(_order_id, _db):
        return order(), {"address_verified": True}, None

    async def pickup(*_args):
        return "560076", "400001", False

    monkeypatch.setattr(couriers, "_load_context", load)
    monkeypatch.setattr(couriers, "_serviceability_query", pickup)
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


@pytest.mark.anyio
async def test_drawer_prefetch_does_not_persist_package_or_selection(monkeypatch, lookup_context):
    monkeypatch.setattr(couriers.OrderOperationsStore, "prepare_courier_lookup", lambda *_args: pytest.fail("prefetch attempted an operations write"))
    monkeypatch.setattr(couriers.OrderOperationsStore, "save_selected_courier", lambda *_args: pytest.fail("prefetch persisted a courier selection"))
    monkeypatch.setattr(couriers.ShiprocketService, "serviceability", lambda *_args: [])
    monkeypatch.setattr(couriers.DelhiveryService, "configured", property(lambda _self: False))
    result = await couriers.shiprocket_serviceability("1", CourierCheckPayload(weight_kg=.5, courier_payment_mode="Prepaid"), SimpleNamespace(), lookup_context)
    assert result["provider"] == "multi"


@pytest.mark.anyio
async def test_explicit_selection_persists_package_before_courier(monkeypatch):
    calls = []
    monkeypatch.setattr(couriers, "current_actor", lambda _request: "Tester")
    monkeypatch.setattr(couriers.OrderOperationsStore, "prepare_courier_lookup", lambda order_id, package, actor: calls.append(("package", order_id, package, actor)))
    monkeypatch.setattr(couriers.OrderOperationsStore, "save_selected_courier", lambda order_id, selected: (calls.append(("courier", order_id, selected)) or {"selected_courier": selected}))
    monkeypatch.setattr(couriers.OrderOperationsStore, "record_timeline_event", lambda *_args, **_kwargs: None)
    payload = {"provider": "shiprocket", "courier_id": "43", "courier_name": "Surface", "booking_supported": True, "weight_kg": .5, "length_cm": 10, "breadth_cm": 11, "height_cm": 12}
    result = await couriers.select_courier("1", payload, SimpleNamespace())
    assert [call[0] for call in calls] == ["package", "courier"]
    assert result["selected_courier"]["courier_id"] == "43"


def test_partial_cod_uses_authoritative_cod_provider_mode():
    partial = order().model_copy(update={"payment_type": "partial_cod"})
    assert couriers._order_payment_mode(partial) == "COD"


@pytest.mark.anyio
async def test_courier_check_readiness_uses_submitted_quote_address(monkeypatch, lookup_context):
    captured_operations = []

    def evaluate(_self, _order, operations, _shipment):
        captured_operations.append(operations)
        result = eligibility()
        result.eligible = operations["corrected_address"]["pincode"] == "400001"
        return result

    async def no_shiprocket_quotes(*_args):
        return []

    monkeypatch.setattr(couriers.ShiprocketService, "evaluate_booking_eligibility", evaluate)
    monkeypatch.setattr(couriers.ShiprocketService, "serviceability", no_shiprocket_quotes)
    monkeypatch.setattr(couriers.DelhiveryService, "configured", property(lambda _self: False))
    payload = CourierCheckPayload(
        weight_kg=.5, courier_payment_mode="Prepaid", drawer_generation=9, client_context_key="drawer-9",
        quote_address={"customer_name": "Lookup", "phone": "9876543210", "address_line1": "Street", "address_line2": "", "landmark": "", "city": "Mumbai", "state": "Maharashtra", "pincode": "400001"},
    )

    result = await couriers.shiprocket_serviceability("1", payload, SimpleNamespace(), lookup_context)

    assert captured_operations[0]["corrected_address"]["pincode"] == "400001"
    assert result["booking_readiness"]["eligible"] is True


@pytest.mark.anyio
async def test_courier_check_readiness_locks_when_quote_address_is_not_verified(monkeypatch):
    address = verified_address("400001")
    cod_order = order().model_copy(update={"payment_type": "cod", "payment_status": "pending"})

    async def load(_order_id, _db):
        return cod_order, {
            "address_verified": True,
            "corrected_address": address,
            "verified_address_snapshot": address,
            "package_details": {"weight_kg": .5, "length_cm": 10, "breadth_cm": 11, "height_cm": 12},
            "call_logs": [{"result": "Confirmed"}],
        }, None

    async def pickup(*_args):
        return "560076", "400002", True

    async def no_shiprocket_quotes(*_args):
        return []

    monkeypatch.setattr(couriers, "_load_context", load)
    monkeypatch.setattr(couriers, "_serviceability_query", pickup)
    monkeypatch.setattr(couriers.ShiprocketService, "serviceability", no_shiprocket_quotes)
    monkeypatch.setattr(couriers.DelhiveryService, "configured", property(lambda _self: False))
    payload = CourierCheckPayload(
        weight_kg=.5, courier_payment_mode="COD", drawer_generation=9, client_context_key="drawer-9",
        quote_address=verified_address("400002"),
    )

    result = await couriers.shiprocket_serviceability("1", payload, SimpleNamespace(), SimpleNamespace(rollback=lambda: None))

    assert result["couriers"]
    assert result["booking_readiness"]["eligible"] is False
    assert "address must be verified" in result["booking_readiness"]["missing_requirements"]


def test_partial_cod_eligibility_uses_cod_requirements_for_partially_paid_status():
    partial = order().model_copy(update={"payment_type": "partial_cod", "payment_status": "partially_paid"})
    address = verified_address()
    operations = {
        "address_verified": True,
        "corrected_address": address,
        "verified_address_snapshot": address,
        "package_details": {"weight_kg": .5, "length_cm": 10, "breadth_cm": 11, "height_cm": 12},
        "call_logs": [],
    }
    service = ShiprocketService(pickup_location="Warehouse")

    pending = service.evaluate_booking_eligibility(partial, operations, None)
    assert pending.payment_mode == "COD"
    assert "latest call must be Confirmed" in pending.missing_requirements

    confirmed = service.evaluate_booking_eligibility(partial, {**operations, "call_logs": [{"result": "Confirmed"}]}, None)
    assert confirmed.payment_mode == "COD"
    assert confirmed.eligible is True


def test_confirmed_cod_still_requires_verified_address_for_booking_readiness():
    cod_order = order().model_copy(update={"payment_type": "cod", "payment_status": "pending"})
    address = verified_address()
    operations = {
        "address_verified": False,
        "corrected_address": address,
        "verified_address_snapshot": None,
        "package_details": {"weight_kg": .5, "length_cm": 10, "breadth_cm": 11, "height_cm": 12},
        "call_logs": [{"result": "Confirmed"}],
    }
    result = ShiprocketService(pickup_location="Warehouse").evaluate_booking_eligibility(cod_order, operations, None)

    assert result.payment_mode == "COD"
    assert result.eligible is False
    assert result.operational_status == "Address Verification Pending"
    assert "address must be verified" in result.missing_requirements


def test_confirmed_cod_with_matching_verified_address_is_booking_ready():
    cod_order = order().model_copy(update={"payment_type": "cod", "payment_status": "pending"})
    address = verified_address()
    operations = {
        # A historic verification can retain a stale boolean flag. The matching snapshot is
        # the canonical evidence for the current persisted address.
        "address_verified": False,
        "corrected_address": address,
        "verified_address_snapshot": address,
        "package_details": {"weight_kg": .5, "length_cm": 10, "breadth_cm": 11, "height_cm": 12},
        "call_logs": [{"result": "Confirmed"}],
    }
    result = ShiprocketService(pickup_location="Warehouse").evaluate_booking_eligibility(cod_order, operations, None)

    assert result.payment_mode == "COD"
    assert result.eligible is True
    assert result.operational_status == "Ready for Booking"


def test_partial_cod_confirmed_still_requires_verified_address():
    partial = order().model_copy(update={"payment_type": "partial_cod", "payment_status": "partially_paid"})
    address = verified_address()
    operations = {
        "address_verified": False,
        "corrected_address": address,
        "verified_address_snapshot": None,
        "package_details": {"weight_kg": .5, "length_cm": 10, "breadth_cm": 11, "height_cm": 12},
        "call_logs": [{"result": "Confirmed"}],
    }
    result = ShiprocketService(pickup_location="Warehouse").evaluate_booking_eligibility(partial, operations, None)

    assert result.payment_mode == "COD"
    assert result.eligible is False
    assert result.operational_status == "Address Verification Pending"
    assert "address must be verified" in result.missing_requirements
