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
CUSTOMER_CANCELLATION_STATUS = "Customer Requested Cancellation"

_SHIPPED_KEYWORDS = ("shipped", "dispatched", "picked up", "in transit", "in_transit", "out for delivery")
_CONFIRMED_BOOKING_STATUSES = {"booked", "complete", "completed", "awb_assigned"}
_UNCERTAIN_BOOKING_STATUSES = {"booking_uncertain", "manifest_unknown", "manifest_partial"}


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _tags_text(order: Any) -> str:
    return " ".join(str(tag) for tag in (getattr(order, "tags", None) or [])).casefold()


def _address_dict(address: Any) -> dict[str, Any] | None:
    if hasattr(address, "model_dump"):
        address = address.model_dump()
    return address if isinstance(address, dict) else None


def _address_value(address: dict[str, Any], key: str) -> str:
    aliases = {
        "customer_name": ("customer_name", "name"),
        "address_line1": ("address_line1", "address"),
    }
    for candidate in aliases.get(key, (key,)):
        value = str(address.get(candidate) or "").strip()
        if value:
            return value.casefold()
    return ""


def has_current_verified_address(order: Any, operations: dict[str, Any] | None) -> bool:
    """A matching persisted verification snapshot is authoritative over a stale flag."""
    operations = operations or {}
    verified = _address_dict(operations.get("verified_address_snapshot"))
    current = _address_dict(operations.get("corrected_address")) or _address_dict(getattr(order, "shipping_address", None))
    if not verified or not current:
        return False
    keys = ("customer_name", "phone", "address_line1", "address_line2", "landmark", "city", "state", "pincode")
    return bool(_address_value(verified, "pincode")) and all(
        _address_value(verified, key) == _address_value(current, key) for key in keys
    )


def has_customer_cancellation_request(order: Any, shipment: dict[str, Any] | None = None) -> bool:
    """Engage order-confirmation value 3 is a request, not Shopify cancellation evidence."""
    value = getattr(order, "order_confirmation", None)
    if value is None:
        value = (shipment or {}).get("order_confirmation")
    return str(value).strip() == "3"


def customer_cancellation_requires_action(order: Any, shipment: dict[str, Any] | None = None) -> bool:
    if not has_customer_cancellation_request(order, shipment):
        return False
    if getattr(order, "cancelled_at", None) or _text(getattr(order, "shopify_status", None)) in {"cancelled", "canceled"}:
        return False
    fulfillment = _text(getattr(order, "fulfillment_status", None))
    provider_status = " ".join(filter(None, [
        _text((shipment or {}).get("normalized_status")),
        _text((shipment or {}).get("latest_status")),
        _text(getattr(getattr(order, "external_tracking", None), "status", None)),
    ]))
    impossible = ("fulfilled", "shipped", "partial", "partially_fulfilled", "delivered")
    lifecycle = ("picked up", "picked_up", "in transit", "in_transit", "out for delivery", "out_for_delivery", "delivered", "rto")
    return fulfillment not in impossible and not any(value in provider_status for value in lifecycle)


def has_persisted_provider_booking_evidence(shipment: dict[str, Any] | None) -> bool:
    """A placeholder row or upstream order created before courier assignment is not booked."""
    shipment = shipment or {}
    if any(str(shipment.get(key) or "").strip() for key in ("awb", "tracking_number", "shopify_tracking_number", "shipment_id")):
        return True
    return bool(
        str(shipment.get("provider_order_id") or "").strip()
        and _text(shipment.get("booking_status")) in _CONFIRMED_BOOKING_STATUSES
    )


def has_uncertain_provider_booking(shipment: dict[str, Any] | None) -> bool:
    """Only a submitted provider request with an unresolved outcome is uncertain."""
    return _text((shipment or {}).get("booking_status")) in _UNCERTAIN_BOOKING_STATUSES


def merge_shopify_fulfillment_evidence(shipment: dict[str, Any] | None, external_tracking: Any | None) -> dict[str, Any] | None:
    """Complete the canonical read model from genuine Shopify tracking; never invent IDs."""
    local = dict(shipment) if shipment else {}
    awb = getattr(external_tracking, "awb", None)
    if not awb:
        return local or None
    provider = getattr(external_tracking, "provider", None)
    local["provider"] = local.get("provider") or provider
    local["courier_name"] = local.get("courier_name") or provider
    local["awb"] = local.get("awb") or awb
    local["shopify_tracking_number"] = local.get("shopify_tracking_number") or awb
    local["tracking_url"] = local.get("tracking_url") or getattr(external_tracking, "tracking_url", None)
    local["latest_status"] = local.get("latest_status") or getattr(external_tracking, "status", None)
    local["booking_status"] = local.get("booking_status") or "confirmed_external"
    local["evidence_source"] = "internal_and_shopify" if shipment and has_persisted_provider_booking_evidence(shipment) else "shopify_fulfillment"
    return local


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
    is_fulfilled = (
        fulfillment_status in {"fulfilled", "shipped", "partial", "partially_fulfilled"}
        and fulfillment_status != "unfulfilled"
    )
    if (
        is_fulfilled
        or any(keyword in tags for keyword in _SHIPPED_KEYWORDS)
        or any(keyword in shipment_status for keyword in _SHIPPED_KEYWORDS)
    ):
        return "Shipped"
    if customer_cancellation_requires_action(order, shipment):
        return CUSTOMER_CANCELLATION_STATUS
    # A Shiprocket order ID only proves that an order exists upstream. Engage sync stores that
    # ID before courier assignment, so booking evidence requires an actual shipment/AWB.
    if has_persisted_provider_booking_evidence(shipment):
        return "Booked"
    if "ndr" in tags:
        return "NDR"
    if latest_call == "On Hold":
        return "On Hold"
    if latest_call == "Wrong Number":
        return "Needs Review"
    payment_type = _text(getattr(order, "payment_type", None))
    if payment_type == "prepaid":
        return "Ready for Booking" if has_current_verified_address(order, operations) else "Address Verification Pending"
    if payment_type in {"cod", "partial_cod"}:
        if latest_call == "Confirmed":
            return "Ready for Booking" if has_current_verified_address(order, operations) else "Address Verification Pending"
        if latest_call == "Callback Requested":
            return "Callback Required"
        return "Call Pending"
    payment_status = _text(getattr(order, "payment_status", None))
    if payment_status and payment_status not in {"pending", "cod", "partially paid", "partially_paid"}:
        return "Ready for Booking" if has_current_verified_address(order, operations) else "Address Verification Pending"
    if latest_call == "Confirmed":
        return "Ready for Booking" if has_current_verified_address(order, operations) else "Address Verification Pending"
    if latest_call == "Callback Requested":
        return "Callback Required"
    return "Call Pending"


def has_existing_shipment_evidence(order: Any, operations: dict[str, Any] | None, shipment: dict[str, Any] | None) -> bool:
    """True if any reliable source - a local shipment record, or Shopify's own fulfilment
    status/tags - shows this order already has an active shipment or fulfilment. This is the
    single gate courier eligibility and the booking endpoint must both honour; it must never be
    possible to reach "eligible" or "booking accepted" once this is true."""
    return derive_operational_status(order, operations, shipment) in SHIPMENT_BACKED_STATUSES
