from __future__ import annotations

from app.services.courier_platform.models import NormalizedShipmentStatus


def normalize_status(value: object) -> NormalizedShipmentStatus:
    text = str(value or "").strip().casefold().replace("_", " ")
    if not text:
        return NormalizedShipmentStatus.UNKNOWN
    if "rto" in text or "return to origin" in text or "return delivered" in text:
        return NormalizedShipmentStatus.RTO
    if "delivered" in text and "undelivered" not in text:
        return NormalizedShipmentStatus.DELIVERED
    if "out for delivery" in text:
        return NormalizedShipmentStatus.OUT_FOR_DELIVERY
    if "ndr" in text or "undelivered" in text:
        return NormalizedShipmentStatus.NDR
    if "cancel" in text:
        return NormalizedShipmentStatus.CANCELLED
    if any(word in text for word in ("exception", "failed", "lost", "damaged")):
        return NormalizedShipmentStatus.EXCEPTION
    if any(word in text for word in ("in transit", "dispatched")):
        return NormalizedShipmentStatus.IN_TRANSIT
    if any(word in text for word in ("picked up", "collected")):
        return NormalizedShipmentStatus.PICKED_UP
    if "pickup" in text:
        return NormalizedShipmentStatus.PICKUP_SCHEDULED
    if any(word in text for word in ("booked", "manifest", "awb assigned", "ready to ship")):
        return NormalizedShipmentStatus.BOOKED
    if any(word in text for word in ("created", "new", "open")):
        return NormalizedShipmentStatus.CREATED
    return NormalizedShipmentStatus.UNKNOWN


def is_terminal(status: NormalizedShipmentStatus) -> bool:
    return status in {NormalizedShipmentStatus.DELIVERED, NormalizedShipmentStatus.RTO, NormalizedShipmentStatus.CANCELLED}
