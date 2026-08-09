from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.shipment_event import ShipmentEvent
from app.services.courier_platform.models import TrackingResult


EVENT_STATUSES = {
    "booked", "pickup_scheduled", "picked_up", "in_transit", "out_for_delivery",
    "delivery_attempted", "ndr", "reattempt", "delivered", "rto_initiated",
    "rto_in_transit", "rto_delivered", "cancelled", "unknown",
}
_SECRET_KEYS = {"authorization", "token", "access_token", "password", "secret", "api_key", "apikey"}
_PII_KEYS = {
    "name", "customer_name", "contact", "phone", "mobile", "email", "address",
    "address_line_1", "address_line_2", "alternate_contact", "sms_contact",
}


def sanitize_provider_event(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).casefold() in _SECRET_KEYS | _PII_KEYS else sanitize_provider_event(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_provider_event(item) for item in value]
    return value


def normalize_event_status(value: object) -> str:
    text = str(value or "").strip().casefold().replace("_", " ").replace("-", " ")
    if not text:
        return "unknown"
    if any(marker in text for marker in ("rto delivered", "returned to seller", "return delivered")):
        return "rto_delivered"
    if any(marker in text for marker in ("rto in transit", "return in transit", "returning to origin")):
        return "rto_in_transit"
    if "rto" in text or "return to origin" in text or "return initiated" in text:
        return "rto_initiated"
    if "reattempt" in text or "re attempt" in text:
        return "reattempt"
    if "ndr" in text or "undeliver" in text or "delivery failed" in text:
        return "ndr"
    if any(marker in text for marker in ("delivery attempted", "attempted delivery", "consignee unavailable")):
        return "delivery_attempted"
    if "out for delivery" in text or text == "ofd":
        return "out_for_delivery"
    if "delivered" in text:
        return "delivered"
    if "cancel" in text:
        return "cancelled"
    if any(marker in text for marker in ("in transit", "dispatched", "bagged", "reached hub", "in scan")):
        return "in_transit"
    if any(marker in text for marker in ("picked up", "pickup complete", "collected")):
        return "picked_up"
    if "pickup" in text or "scheduled" in text:
        return "pickup_scheduled"
    if any(marker in text for marker in ("booked", "manifest", "awb assigned", "ready to ship", "created", "new")):
        return "booked"
    return "unknown"


def _parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for parser in (
        lambda: datetime.fromisoformat(text),
        lambda: datetime.strptime(text, "%Y-%m-%d %H:%M:%S"),
        lambda: datetime.strptime(text, "%d %b %Y, %I:%M %p"),
    ):
        try:
            parsed = parser()
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _shiprocket_events(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    data = raw.get("tracking_data") or raw.get("data") or raw
    if not isinstance(data, dict):
        return []
    activities = data.get("shipment_track_activities") or data.get("activities") or []
    return [
        {
            "code": item.get("sr-status-label") or item.get("status_code") or item.get("status"),
            "status": item.get("status") or item.get("activity") or item.get("sr-status-label"),
            "timestamp": item.get("date") or item.get("created_at") or item.get("timestamp"),
            "location": item.get("location"),
            "message": item.get("activity") or item.get("status"),
            "reason": item.get("reason"),
            "raw": item,
        }
        for item in activities if isinstance(item, dict)
    ]


def _delhivery_events(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    payload = raw.get("raw") if isinstance(raw.get("raw"), dict) else raw
    packages = payload.get("ShipmentData") or payload.get("shipments") or payload.get("data") or []
    if not isinstance(packages, list) or not packages:
        return []
    wrapper = packages[0] if isinstance(packages[0], dict) else {}
    shipment = wrapper.get("Shipment") if isinstance(wrapper.get("Shipment"), dict) else wrapper
    scans = shipment.get("Scans") if isinstance(shipment.get("Scans"), list) else []
    values = []
    for wrapper in scans:
        item = wrapper.get("ScanDetail") if isinstance(wrapper, dict) and isinstance(wrapper.get("ScanDetail"), dict) else wrapper
        if not isinstance(item, dict):
            continue
        values.append({
            "code": item.get("ScanType") or item.get("StatusCode") or item.get("Scan"),
            "status": item.get("Scan") or item.get("Status"),
            "timestamp": item.get("ScanDateTime") or item.get("StatusDateTime"),
            "location": item.get("ScannedLocation") or item.get("Location"),
            "message": item.get("Instructions") or item.get("Scan"),
            "reason": item.get("Remarks"),
            "raw": item,
        })
    return values


def _shadowfax_events(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    payload = raw.get("provider_response") if isinstance(raw.get("provider_response"), dict) else raw
    activities = payload.get("tracking_details") or []
    return [
        {
            "code": item.get("status_id") or item.get("status"),
            "status": item.get("status_id") or item.get("status"),
            "timestamp": item.get("created"),
            "location": item.get("location"),
            "message": item.get("remarks") or item.get("status"),
            "reason": item.get("failure_reason") or item.get("ndr_reason"),
            "raw": item,
        }
        for item in activities if isinstance(item, dict)
    ]


def extract_tracking_events(result: TrackingResult) -> list[dict[str, Any]]:
    extractor = {"shiprocket": _shiprocket_events, "delhivery": _delhivery_events, "shadowfax": _shadowfax_events}.get(result.provider)
    events = extractor(result.raw_response) if extractor else []
    if events:
        return events
    # A tracking response is itself a current provider observation, not a fabricated historical backfill.
    return [{
        "code": result.provider_status,
        "status": result.provider_status or result.status.value,
        "timestamp": result.latest_tracking_at,
        "location": result.latest_scan,
        "message": result.courier_remarks,
        "reason": result.ndr_reason,
        "raw": None,
    }]


def _deduplication_key(*, provider: str, order_id: str, awb: str | None, event: dict[str, Any], normalized: str, occurred_at: datetime | None) -> str:
    stable = json.dumps({
        "provider": provider, "order_id": order_id, "awb": awb,
        "code": str(event.get("code") or ""), "status": normalized,
        "provider_event_at": occurred_at.isoformat() if occurred_at else None,
        "location": str(event.get("location") or ""),
        "message": str(event.get("message") or ""),
        "reason": str(event.get("reason") or ""),
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(stable.encode()).hexdigest()


def append_tracking_events(
    db: Session, *, order_id: str, shipment: dict[str, Any], result: TrackingResult,
    source: str, order_number: str | None = None,
) -> list[ShipmentEvent]:
    inserted: list[ShipmentEvent] = []
    provider = str(result.provider or shipment.get("provider") or "unknown").casefold()
    awb = str(shipment.get("awb") or "").strip() or None
    for item in extract_tracking_events(result):
        occurred_at = item.get("timestamp") if isinstance(item.get("timestamp"), datetime) else _parse_datetime(item.get("timestamp"))
        normalized = normalize_event_status(item.get("status") or item.get("code"))
        key = _deduplication_key(provider=provider, order_id=order_id, awb=awb, event=item, normalized=normalized, occurred_at=occurred_at)
        if db.scalar(select(ShipmentEvent.id).where(ShipmentEvent.deduplication_key == key)):
            continue
        event = ShipmentEvent(
            id=uuid4().hex, order_id=order_id, order_number=order_number,
            shipment_reference=str(shipment.get("shipment_id") or shipment.get("provider_order_id") or "").strip() or None,
            provider=provider, courier_service=str(shipment.get("courier_service") or shipment.get("courier_name") or "").strip() or None,
            awb=awb, provider_status_code=str(item.get("code") or "").strip() or None,
            normalized_status=normalized, provider_event_at=occurred_at, recorded_at=datetime.now(timezone.utc),
            location=str(item.get("location") or "").strip() or None,
            message=str(item.get("message") or "").strip() or None,
            reason=str(item.get("reason") or "").strip() or None,
            raw_provider_event=json.dumps(sanitize_provider_event(item.get("raw")), separators=(",", ":"), ensure_ascii=True) if item.get("raw") is not None else None,
            source=source, deduplication_key=key,
        )
        try:
            with db.begin_nested():
                db.add(event)
                db.flush()
        except IntegrityError:
            continue
        inserted.append(event)
    db.commit()
    return inserted


def shipment_event_history(db: Session, order_id: str) -> list[dict[str, Any]]:
    events = db.scalars(
        select(ShipmentEvent).where(ShipmentEvent.order_id == order_id)
        .order_by(ShipmentEvent.provider_event_at.asc().nulls_last(), ShipmentEvent.recorded_at.asc())
    ).all()
    return [{
        "id": event.id, "order_id": event.order_id, "order_number": event.order_number,
        "shipment_reference": event.shipment_reference, "provider": event.provider,
        "courier_service": event.courier_service, "awb": event.awb,
        "provider_status_code": event.provider_status_code, "normalized_status": event.normalized_status,
        "provider_event_at": event.provider_event_at.isoformat() if event.provider_event_at else None,
        "recorded_at": event.recorded_at.isoformat(), "location": event.location,
        "message": event.message, "reason": event.reason,
        "raw_provider_event": json.loads(event.raw_provider_event) if event.raw_provider_event else None,
        "source": event.source, "deduplication_key": event.deduplication_key,
    } for event in events]
