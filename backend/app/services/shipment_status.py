"""Single authoritative source for order operational-status precedence and existing-shipment
detection.

Regression fixed 2026-07-21: locally-derived operational states (call-log results, address
verification) were able to override/hide a shipment that already exists - either booked through
Mumchies OS or fulfilled directly in Shopify. Every caller that needs "what status should this
order show" or "is this order already shipped" must go through this module rather than
re-deriving the precedence independently, so the rule can never drift out of sync between the
order list, booking eligibility, and the booking endpoint.
"""

from __future__ import annotations

from typing import Any

# States backed by an actual shipment/fulfilment record. These always outrank locally-derived
# operational states (Ready for Booking, Address Verification Pending, Call Pending, ...) and,
# once reached, block courier eligibility and booking.
SHIPMENT_BACKED_STATUSES = {"Booked", "Shipped", "In Transit", "Out for Delivery", "Delivered", "NDR"}

_SHIPPED_KEYWORDS = ("shipped", "dispatched", "picked up", "in transit", "in_transit", "out for delivery")


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _tags_text(order: Any) -> str:
    return " ".join(str(tag) for tag in (getattr(order, "tags", None) or [])).casefold()


def derive_operational_status(order: Any, operations: dict[str, Any] | None, shipment: dict[str, Any] | None) -> str:
    """The one authoritative precedence chain. Shipment/fulfilment-backed states (Cancelled,
    Delivered, Shipped, Booked, NDR) always outrank locally-derived operational states - a call
    log or address edit can update operational metadata but must never downgrade a shipment
    lifecycle status back to something like "Ready for Booking"."""
    operations = operations or {}
    call_logs = operations.get("call_logs") or []
    latest_call = call_logs[0]["result"] if call_logs else None
    cancelled_at = getattr(order, "cancelled_at", None)
    shopify_status = _text(getattr(order, "shopify_status", None))
    fulfillment_status = _text(getattr(order, "fulfillment_status", None))
    tags = _tags_text(order)
    shipment_status = _text((shipment or {}).get("latest_status"))

    if shopify_status == "cancelled" or fulfillment_status == "cancelled" or cancelled_at:
        return "Cancelled"
    if "delivered" in tags or fulfillment_status == "delivered" or "delivered" in shipment_status:
        return "Delivered"
    if (
        "fulfilled" in fulfillment_status
        or "partial" in fulfillment_status
        or any(keyword in tags for keyword in _SHIPPED_KEYWORDS)
        or any(keyword in shipment_status for keyword in _SHIPPED_KEYWORDS)
    ):
        return "Shipped"
    if shipment and any(shipment.get(key) for key in ("awb", "shipment_id", "shiprocket_order_id")):
        return "Booked"
    if "ndr" in tags:
        return "NDR"
    if latest_call == "Wrong Number":
        return "Needs Review"
    payment_status = _text(getattr(order, "payment_status", None))
    if payment_status and payment_status not in {"pending", "cod", "partially paid"}:
        return "Ready for Booking" if operations.get("address_verified") else "Address Verification Pending"
    if latest_call == "Confirmed":
        return "Ready for Booking"
    if latest_call == "Callback Requested":
        return "Callback Required"
    return "Call Pending"


def has_existing_shipment_evidence(order: Any, operations: dict[str, Any] | None, shipment: dict[str, Any] | None) -> bool:
    """True if any reliable source - a local shipment record, or Shopify's own fulfilment
    status/tags - shows this order already has an active shipment or fulfilment. This is the
    single gate courier eligibility and the booking endpoint must both honour; it must never be
    possible to reach "eligible" or "booking accepted" once this is true."""
    return derive_operational_status(order, operations, shipment) in SHIPMENT_BACKED_STATUSES
