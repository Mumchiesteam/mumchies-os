from decimal import Decimal

import pytest

from app.schemas.orders import ShopifyOrder
from app.services.repeat_customers import mark_repeat_customers, normalize_indian_phone


def order(number: str, created: str, *, customer_id: str | None, phone: str | None, email: str | None) -> ShopifyOrder:
    return ShopifyOrder(
        order_id=number, order_number=number, created_date=created, customer_id=customer_id,
        phone=phone, email=email, products=[], total_amount=Decimal("1"), tags=[],
    )


def history(number: str, created: str, *, customer_id: str | None = None, phone: str | None = None,
            email: str | None = None, cancelled: bool = False, test: bool = False) -> dict:
    return {
        "id": number, "created_at": created, "customer": {"id": customer_id, "phone": phone, "email": email} if customer_id or phone or email else None,
        "phone": phone, "email": email, "shipping_address": {"phone": phone},
        "cancelled_at": created if cancelled else None, "test": test, "tags": "",
    }


@pytest.mark.parametrize("value", ["9871064928", "+919871064928", "919871064928", "+91 98710 64928"])
def test_indian_phone_formats_are_equivalent(value: str):
    assert normalize_indian_phone(value) == "9871064928"


def test_325670_shape_is_repeat_from_earlier_fulfilled_customer_order():
    current = order("325670", "2026-08-22T20:04:18+05:30", customer_id="9753995837518", phone="+919871064928", email="parveendda1966@gmail.com")
    rows = [
        history("325670", current.created_date, customer_id=current.customer_id, phone=current.phone, email=current.email),
        history("325320", "2026-08-18T00:46:06+05:30", customer_id=current.customer_id, phone="9871064928", email="PARVEENDDA1966@gmail.com "),
    ]
    assert mark_repeat_customers([current], rows)[0].is_repeat_customer is True


def test_identity_hierarchy_falls_back_to_phone_then_email_without_name_matching():
    current_phone = order("2", "2026-08-22T00:00:00Z", customer_id=None, phone="+91 98710 64928", email=None)
    current_email = order("3", "2026-08-22T00:00:00Z", customer_id=None, phone=None, email=" Person@Example.com ")
    rows = [history("1", "2026-08-01T00:00:00Z", customer_id="old", phone="919871064928"), history("0", "2026-07-01T00:00:00Z", email="person@example.com")]
    assert [value.is_repeat_customer for value in mark_repeat_customers([current_phone, current_email], rows)] == [True, True]


def test_current_future_cancelled_and_test_orders_do_not_make_repeat():
    current = order("2", "2026-08-22T00:00:00Z", customer_id="c1", phone=None, email=None)
    rows = [
        history("2", current.created_date, customer_id="c1"),
        history("3", "2026-08-23T00:00:00Z", customer_id="c1"),
        history("0", "2026-08-01T00:00:00Z", customer_id="c1", cancelled=True),
        history("-1", "2026-07-01T00:00:00Z", customer_id="c1", test=True),
    ]
    assert mark_repeat_customers([current], rows)[0].is_repeat_customer is False


def test_customer_id_is_authoritative_over_reused_phone_and_email():
    current = order("2", "2026-08-22T00:00:00Z", customer_id="new", phone="9871064928", email="same@example.com")
    rows = [history("1", "2026-08-01T00:00:00Z", customer_id="old", phone="9871064928", email="same@example.com")]
    assert mark_repeat_customers([current], rows)[0].is_repeat_customer is False
