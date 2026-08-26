"""Authoritative repeat-customer matching over a bulk Shopify order history."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.schemas.orders import ShopifyOrder


def normalize_indian_phone(value: object) -> str | None:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def normalize_email(value: object) -> str | None:
    normalized = str(value or "").strip().casefold()
    return normalized or None


def _instant(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _genuine(value: dict[str, Any]) -> bool:
    tags = {tag.strip().casefold() for tag in str(value.get("tags") or "").split(",")}
    return not value.get("cancelled_at") and not bool(value.get("test")) and not tags.intersection({"test", "test order"})


def mark_repeat_customers(orders: Iterable[ShopifyOrder], history: Iterable[dict[str, Any]]) -> list[ShopifyOrder]:
    """Mark current orders when a genuine, strictly earlier order matches the identity hierarchy."""
    history_rows = [value for value in history if _genuine(value)]
    by_customer: dict[str, list[datetime]] = {}
    by_phone: dict[str, list[datetime]] = {}
    by_email: dict[str, list[datetime]] = {}
    for value in history_rows:
        try:
            created = _instant(value["created_at"])
        except (KeyError, TypeError, ValueError):
            continue
        customer = value.get("customer") or {}
        address = value.get("shipping_address") or {}
        customer_id = str(customer.get("id")) if customer.get("id") is not None else None
        phone = normalize_indian_phone(value.get("phone") or customer.get("phone") or address.get("phone"))
        email = normalize_email(value.get("email") or customer.get("email"))
        if customer_id:
            by_customer.setdefault(customer_id, []).append(created)
        if phone:
            by_phone.setdefault(phone, []).append(created)
        if email:
            by_email.setdefault(email, []).append(created)

    result: list[ShopifyOrder] = []
    for order in orders:
        created = _instant(order.created_date)
        phone = normalize_indian_phone(order.phone)
        email = normalize_email(order.email)
        if order.customer_id:
            repeat = any(value < created for value in by_customer.get(order.customer_id, []))
        else:
            repeat = bool(
                (phone and any(value < created for value in by_phone.get(phone, [])))
                or (email and any(value < created for value in by_email.get(email, [])))
            )
        result.append(order.model_copy(update={"is_repeat_customer": repeat}))
    return result
