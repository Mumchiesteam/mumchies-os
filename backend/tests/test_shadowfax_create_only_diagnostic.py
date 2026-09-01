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
async def test_create_only_diagnostic_calls_only_shadowfax_create_and_never_persists(monkeypatch):
    raw = raw_order(status="paid", outstanding="0")
    raw["shipping_address"].update({"phone": "9999999999", "zip": "560076"})
    raw["payment_gateway_names"] = ["Razorpay"]
    order = ShopifyService._to_order(raw)
    operations = {
        "package_details": {"weight_kg": 0.5, "length_cm": 10, "breadth_cm": 8, "height_cm": 6},
    }
    calls: list[str] = []

    async def load_context(order_id, received_db):
        assert order_id == order.order_id
        assert received_db is None
        return order, operations, None

    async def no_shiprocket_call(*_args, **_kwargs):
        raise AssertionError("create-only diagnostic must not call Shiprocket")

    class Adapter:
        async def create_booking(self, payload):
            calls.append("shadowfax.create_booking")
            assert payload["order_type"] == "warehouse"
            assert payload["order_details"]["client_name"] == "Mumchies Foods"
            return SimpleNamespace(
                raw_response={"http_status": 201, "message": "Success", "data": {"id": 4501, "awb_number": "SF-TEST-1"}},
            )

    monkeypatch.setattr(shadowfax, "_load_context", load_context)
    monkeypatch.setattr(shadowfax, "_cached_shiprocket_pickup_location_details", lambda: {
        "name": "Mumchies Foods", "phone": "9876543210", "address": "Warehouse Road",
        "city": "Bengaluru", "state": "Karnataka", "postal_code": "560076",
    })
    monkeypatch.setattr(couriers.ShiprocketService, "pickup_location_details", no_shiprocket_call)
    monkeypatch.setattr(shadowfax, "ShadowfaxAdapter", Adapter)
    shadowfax._create_only_attempted_order_ids.clear()

    result = await shadowfax.shadowfax_create_only_diagnostic(order.order_id, admin_request(), None)

    assert calls == ["shadowfax.create_booking"]
    assert result == {
        "outcome": "success", "http_status": 201, "message": "Success", "validation_errors": None,
        "data": {"id": 4501, "awb_number": "SF-TEST-1"},
        "payload": {
            "order_type": "warehouse", "client_order_id": order.order_number, "client_name": "Mumchies Foods",
            "payment_mode": "Prepaid", "cod_amount": 0, "total_amount": float(order.order_total),
            "actual_weight_g": 500, "volumetric_weight_g": 96, "customer_pincode": 560076,
            "pickup_pincode": 560076, "rto_pincode": 560076, "product_count": 1,
        },
    }
    with pytest.raises(Exception) as error:
        await shadowfax.shadowfax_create_only_diagnostic(order.order_id, admin_request(), None)
    assert getattr(error.value, "status_code", None) == 409
    assert calls == ["shadowfax.create_booking"]


@pytest.mark.anyio
async def test_create_only_diagnostic_stops_without_cached_pickup_before_shadowfax(monkeypatch):
    raw = raw_order(status="paid", outstanding="0")
    raw["shipping_address"].update({"phone": "9999999999", "zip": "560076"})
    raw["payment_gateway_names"] = ["Razorpay"]
    order = ShopifyService._to_order(raw)

    async def load_context(_order_id, _db):
        return order, {"package_details": {"weight_kg": 0.5, "length_cm": 10, "breadth_cm": 8, "height_cm": 6}}, None

    monkeypatch.setattr(shadowfax, "_load_context", load_context)
    monkeypatch.setattr(shadowfax, "_cached_shiprocket_pickup_location_details", lambda: None)
    shadowfax._create_only_attempted_order_ids.clear()

    with pytest.raises(Exception) as error:
        await shadowfax.shadowfax_create_only_diagnostic(order.order_id, admin_request(), None)

    assert getattr(error.value, "status_code", None) == 409
    assert "will not call Shiprocket" in str(getattr(error.value, "detail", ""))
