from __future__ import annotations

from types import SimpleNamespace
import pytest

from app.schemas.orders import ShopifyOrder, ShippingAddress
from app.services.shipment_status import derive_operational_status, has_existing_shipment_evidence
from app.services.shiprocket import ShiprocketService


def test_address_verification_no_warnings():
    """1. Verification with no warnings: status becomes verified and booking can proceed."""
    order = SimpleNamespace(
        payment_status="paid",
        shopify_status=None,
        fulfillment_status="unfulfilled",
        tags=[],
        cancelled_at=None,
        shipping_address=ShippingAddress(
            name="John Doe",
            address="123 Main St",
            landmark="Near Park",
            city="Mumbai",
            state="Maharashtra",
            pincode="400001",
        ),
    )
    operations = {
        "address_verified": True,
        "address_verification_status": "verified",
        "verified_address_snapshot": {
            "customer_name": "John Doe",
            "phone": "9999999999",
            "address_line1": "123 Main St",
            "address_line2": "",
            "landmark": "Near Park",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pincode": "400001",
        },
        "package_details": {"weight_kg": 0.5, "length_cm": 10, "breadth_cm": 10, "height_cm": 10},
    }
    
    status = derive_operational_status(order, operations, None)
    assert status == "Ready for Booking"
    
    service = ShiprocketService()
    service.pickup_location = "Primary"
    eligibility = service.evaluate_booking_eligibility(order, operations, None)
    assert eligibility.eligible is True
    assert eligibility.shipment_exists is False
    assert "address must be verified" not in eligibility.missing_requirements


def test_unfulfilled_order_not_treated_as_shipped_or_booked():
    """Unfulfilled order with fulfillment_status='unfulfilled' must NOT be classified as Shipped/Booked."""
    order = SimpleNamespace(
        payment_status="paid",
        shopify_status="unfulfilled",
        fulfillment_status="unfulfilled",
        tags=["prepaid"],
        cancelled_at=None,
        shipping_address=ShippingAddress(
            name="Test User",
            address="123 Street",
            city="Delhi",
            state="Delhi",
            pincode="110001",
        ),
    )
    operations = {
        "address_verified": True,
        "address_verification_status": "verified",
        "package_details": {"weight_kg": 1, "length_cm": 10, "breadth_cm": 10, "height_cm": 10},
    }

    status = derive_operational_status(order, operations, None)
    assert status == "Ready for Booking"
    assert status != "Shipped"
    assert status != "Booked"
    assert has_existing_shipment_evidence(order, operations, None) is False


def test_real_provider_shipment_id_or_awb_treated_as_booked():
    """Real provider shipment ID or AWB present: shipment treated as booked."""
    order = SimpleNamespace(
        payment_status="paid",
        shopify_status=None,
        fulfillment_status="unfulfilled",
        tags=[],
        cancelled_at=None,
        shipping_address=ShippingAddress(name="John Doe", pincode="400001"),
    )
    operations = {
        "address_verified": True,
        "address_verification_status": "verified",
        "shipment": {"shipment_id": "SR12345", "awb": "123456789"},
    }

    status = derive_operational_status(order, operations, operations["shipment"])
    assert status == "Booked"

    service = ShiprocketService()
    service.pickup_location = "Primary"
    eligibility = service.evaluate_booking_eligibility(order, operations, operations["shipment"])
    assert eligibility.shipment_exists is True
    assert "an active shipment or fulfilment already exists for this order" in eligibility.missing_requirements


def test_failed_booking_attempt_allows_retry():
    """Failed booking attempt without shipment creation: retry remains allowed."""
    order = SimpleNamespace(
        payment_status="paid",
        shopify_status=None,
        fulfillment_status="unfulfilled",
        tags=[],
        cancelled_at=None,
        shipping_address=ShippingAddress(
            name="John Doe",
            address="123 Main St",
            city="Mumbai",
            state="Maharashtra",
            pincode="400001",
        ),
    )
    operations = {
        "address_verified": True,
        "address_verification_status": "verified",
        "verified_address_snapshot": {
            "customer_name": "John Doe",
            "phone": "9999999999",
            "address_line1": "123 Main St",
            "address_line2": "",
            "landmark": "",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pincode": "400001",
        },
        "courier_sync_status": "failed",
        "courier_sync_error": "API timeout",
        "package_details": {"weight_kg": 0.5, "length_cm": 10, "breadth_cm": 10, "height_cm": 10},
    }

    status = derive_operational_status(order, operations, None)
    assert status == "Ready for Booking"

    service = ShiprocketService()
    service.pickup_location = "Primary"
    eligibility = service.evaluate_booking_eligibility(order, operations, None)
    assert eligibility.eligible is True
    assert eligibility.shipment_exists is False


def test_address_verification_advisory_warning():
    """2. Verification with advisory warning such as missing landmark: status still becomes verified."""
    order = SimpleNamespace(
        payment_status="paid",
        shopify_status=None,
        fulfillment_status="unfulfilled",
        tags=[],
        cancelled_at=None,
        shipping_address=ShippingAddress(
            name="Jane Doe",
            address="456 Elm St",
            landmark=None,
            city="Mira Road",
            state="Maharashtra",
            pincode="401101",
        ),
    )
    operations = {
        "address_verified": True,
        "address_verification_status": "verified",
        "verified_address_snapshot": {
            "customer_name": "Jane Doe",
            "phone": "9999999999",
            "address_line1": "456 Elm St",
            "address_line2": "",
            "landmark": "",
            "city": "Mira Road",
            "state": "Maharashtra",
            "pincode": "401101",
        },
        "package_details": {"weight_kg": 0.5, "length_cm": 5, "breadth_cm": 5, "height_cm": 5},
    }

    status = derive_operational_status(order, operations, None)
    assert status == "Ready for Booking"

    service = ShiprocketService()
    service.pickup_location = "Primary"
    eligibility = service.evaluate_booking_eligibility(order, operations, None)
    assert eligibility.eligible is True
    assert eligibility.operational_status == "Ready for Booking"
    assert "address must be verified" not in eligibility.missing_requirements
    assert "operational status must be Ready for Booking" not in eligibility.missing_requirements


def test_address_genuinely_pending():
    """5. Address genuinely pending: Book Shipment remains disabled with a clear blocker."""
    order = SimpleNamespace(
        payment_status="paid",
        shopify_status=None,
        fulfillment_status="unfulfilled",
        tags=[],
        cancelled_at=None,
        shipping_address=ShippingAddress(name="Jane Doe", pincode="401101"),
    )
    operations = {
        "address_verified": False,
        "address_verification_status": "pending",
    }

    status = derive_operational_status(order, operations, None)
    assert status == "Address Verification Pending"

    service = ShiprocketService()
    service.pickup_location = "Primary"
    eligibility = service.evaluate_booking_eligibility(order, operations, None)
    assert eligibility.eligible is False
    assert "address must be verified" in eligibility.missing_requirements
    assert "operational status must be Ready for Booking" in eligibility.missing_requirements
