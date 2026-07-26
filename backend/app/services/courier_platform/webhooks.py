from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shiprocket import CourierWebhookEvent
from app.repositories.shiprocket import get_shipment, upsert_shipment
from app.services.courier_platform.base import ProviderError
from app.services.courier_platform.models import TrackingResult
from app.services.order_operations import OrderOperationsStore

Verifier = Callable[[bytes, dict[str, str]], bool]
Normalizer = Callable[[dict[str, Any]], tuple[str, str, TrackingResult]]


class WebhookHandler:
    def __init__(self, verify: Verifier, normalize: Normalizer) -> None:
        self.verify, self.normalize = verify, normalize


class WebhookRegistry:
    def __init__(self) -> None: self._handlers: dict[str, WebhookHandler] = {}
    def register(self, provider: str, handler: WebhookHandler) -> None: self._handlers[provider.casefold()] = handler
    def get(self, provider: str) -> WebhookHandler | None: return self._handlers.get(provider.casefold())


webhook_registry = WebhookRegistry()


def process_webhook(db: Session, *, provider: str, body: bytes, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    handler = webhook_registry.get(provider)
    if handler is None:
        raise ProviderError("Official webhook verification is not configured for this provider.", provider=provider, operation="webhook")
    if not handler.verify(body, headers):
        raise ProviderError("Webhook signature verification failed.", provider=provider, operation="webhook")
    event_id, order_id, tracking = handler.normalize(payload)
    existing = db.scalars(select(CourierWebhookEvent).where(CourierWebhookEvent.provider == provider, CourierWebhookEvent.provider_event_id == event_id)).first()
    if existing:
        return {"accepted": True, "duplicate": True, "event_id": event_id}
    event = CourierWebhookEvent(id=uuid4().hex, provider=provider, provider_event_id=event_id, order_id=order_id, payload_hash=hashlib.sha256(body).hexdigest(), received_at=datetime.now(timezone.utc), status="received")
    db.add(event); db.commit()
    shipment = get_shipment(db, order_id)
    if shipment is None or shipment.provider != provider:
        event.status, event.error = "manual_review", "Shipment mapping was not found."
        db.commit()
        return {"accepted": True, "duplicate": False, "manual_review": True, "event_id": event_id}
    upsert_shipment(db, order_id, latest_status=tracking.provider_status or tracking.status.value, normalized_status=tracking.status.value, latest_scan=tracking.latest_scan, latest_tracking_at=tracking.latest_tracking_at, terminal_status=tracking.status.value if tracking.terminal else None, ndr_reason=tracking.ndr_reason, ndr_attempt=tracking.ndr_attempt, ndr_remarks=tracking.courier_remarks, last_synced_at=datetime.now(timezone.utc))
    event.status, event.processed_at = "processed", datetime.now(timezone.utc)
    db.commit()
    OrderOperationsStore.record_timeline_event(order_id, "courier_webhook", operator=provider, details={"event_id": event_id, "status": tracking.status.value})
    return {"accepted": True, "duplicate": False, "event_id": event_id}
