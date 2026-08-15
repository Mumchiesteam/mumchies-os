from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.couriers import PackageDetailsPayload, _assert_booking_payload, _booking_context, _build_delhivery_payload, _context_operations
from app.api.routes import orders as order_routes
from app.services import order_operations
from app.services.order_operations import OrderOperationsStore
from app.services.shopify import ShopifyService
from tests.test_operations_upgrade import raw_order


def order(identity: int, number: str, name: str, city: str, pin: str, product: str):
    value = raw_order(status="pending", outstanding="508")
    value.update({"id": identity, "name": f"#{number}", "order_number": int(number), "customer": {"first_name": name},
                  "shipping_address": {"name": name, "phone": "9999999999", "address1": "Address", "city": city, "province": "Maharashtra", "zip": pin},
                  "line_items": [{"title": product, "sku": "SKU", "quantity": 1, "grams": 950, "price": "508"}],
                  "total_price": "508", "current_total_price": "508", "total_outstanding": "508", "payment_gateway_names": ["COD"]})
    return ShopifyService._to_order(value)


def selected():
    return {"provider": "delhivery", "courier_id": "delhivery:surface", "courier_name": "Delhivery Surface", "booking_supported": True}


def package_ops(extra=None):
    return {"package_details": PackageDetailsPayload(weight_kg=.95).model_dump(), "package_revision": 1, "package_provenance": {"order_id": "695", "revision": 1}, **(extra or {})}


def test_legacy_anonymous_override_is_blocked():
    b = order(695, "324695", "Parveen", "Pune", "411036", "Millet Noodles")
    with pytest.raises(HTTPException, match="provenance"):
        _booking_context(b, package_ops({"corrected_address": {"customer_name": "Saurabh", "pincode": "416416"}}), PackageDetailsPayload(weight_kg=.95), selected())


def test_valid_same_order_override_is_allowed():
    b = order(695, "324695", "Parveen", "Pune", "411036", "Millet Noodles")
    address = {"customer_name": "Parveen", "phone": "9999999999", "address_line1": "New address", "city": "Pune", "state": "Maharashtra", "pincode": "411037"}
    ops = package_ops({"corrected_address": address, "address_revision": 2, "address_provenance": {"order_id": "695", "revision": 2}})
    assert _booking_context(b, ops, PackageDetailsPayload(weight_kg=.95), selected()).address["pincode"] == "411037"


def test_exact_324692_to_324695_mixed_payload_never_passes_integrity_assertion():
    a = order(692, "324692", "Saurabh", "Sangli", "416416", "Besan Laddu")
    b = order(695, "324695", "Parveen", "Pune", "411036", "Millet Noodles")
    context = _booking_context(b, package_ops(), PackageDetailsPayload(weight_kg=.95), selected())
    contaminated = _build_delhivery_payload(b, {"corrected_address": a.shipping_address.model_dump()}, context.package)
    assert contaminated["order"] == "324695" and contaminated["pin"] == "416416"
    with pytest.raises(HTTPException, match="Booking blocked"):
        _assert_booking_payload(context, "delhivery", contaminated)


def test_context_payload_for_one_order_passes():
    b = order(695, "324695", "Parveen", "Pune", "411036", "Millet Noodles")
    context = _booking_context(b, package_ops(), PackageDetailsPayload(weight_kg=.95), selected())
    payload = _build_delhivery_payload(context.order, _context_operations(context), context.package)
    _assert_booking_payload(context, "delhivery", payload)


def test_same_order_optimistic_concurrency_rejects_second_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "operations.json")
    address = {"customer_name": "Parveen", "pincode": "411036"}
    first = OrderOperationsStore.save_verified_address_if_current("695", address, expected_revision=0, visible_order_number="324695", operator="one", verified=True)
    assert first["address_revision"] == 1
    with pytest.raises(ValueError, match="stale_address_revision:1"):
        OrderOperationsStore.save_verified_address_if_current("695", address, expected_revision=0, visible_order_number="324695", operator="two", verified=True)


def test_server_signed_draft_for_order_a_cannot_be_relabelled_as_order_b(monkeypatch):
    monkeypatch.setattr(order_routes.settings, "auth_session_secret", "test-secret")
    token_a = order_routes._address_draft_token("692", 0)
    with pytest.raises(HTTPException, match="identity"):
        order_routes._assert_address_draft_token("695", 0, token_a)
