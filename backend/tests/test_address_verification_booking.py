from __future__ import annotations

from types import SimpleNamespace
import pytest

from app.schemas.orders import ShopifyOrder, ShippingAddress
from app.services.shipment_status import derive_operational_status
from app.services.shiprocket import ShiprocketService


def test_address_verification_no_warnings():
    """1. Verification with no warnings: status becomes verified and booking can proceed."""
    order = SimpleNamespace(
        payment_status="paid",
        shopify_status=None,
        fulfillment_status=None,
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
    assert "address must be verified" not in eligibility.missing_requirements


def test_address_verification_advisory_warning():
    """2. Verification with advisory warning such as missing landmark: status still becomes verified."""
    order = SimpleNamespace(
        payment_status="paid",
        shopify_status=None,
        fulfillment_status=None,
        tags=[],
        cancelled_at=None,
        shipping_address=ShippingAddress(
            name="Jane Doe",
            address="456 Elm St",
            landmark=None,  # Landmark is missing advisory
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
        fulfillment_status=None,
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
