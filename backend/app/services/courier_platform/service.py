from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.shiprocket import get_shipment, snapshot, upsert_shipment
from app.services.courier_platform.base import CourierAdapter, ProviderConfigurationError, ProviderError
from app.services.courier_platform.models import BookingConfidence, BookingResult, NormalizedShipmentStatus, ReconciliationStatus
from app.services.order_operations import OrderOperationsStore
from app.services.shipment_status import has_persisted_provider_booking_evidence, has_uncertain_provider_booking
from app.services.shipment_events import append_tracking_events, extract_tracking_events


def _json(value: Any) -> str | None:
    def encode(item: Any) -> str:
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, default=encode) if value is not None else None


class CourierPlatformService:
    """Provider-neutral orchestration. Provider adapters only translate official HTTP contracts."""
    async def book(self, db: Session, *, order_id: str, merchant_order_id: str, adapter: CourierAdapter,
                   request: dict[str, Any], operator: str) -> dict[str, Any]:
        existing = get_shipment(db, order_id)
        if existing and has_persisted_provider_booking_evidence(snapshot(existing)):
            if existing.provider != adapter.provider:
                raise ProviderError(f"Order is already associated with {existing.provider}.", provider=adapter.provider, operation="booking")
            return {"shipment": snapshot(existing), "existing": True}
        if existing and has_uncertain_provider_booking(snapshot(existing)):
            raise ProviderError("A submitted booking has an uncertain outcome. Reconcile it before retrying.", provider=adapter.provider, operation="booking", uncertain=True)

        try:
            upstream = await adapter.reconcile_booking(merchant_order_id)
        except ProviderConfigurationError as error:
            unsupported_shadowfax_lookup = (
                adapter.provider == "shadowfax"
                and error.operation == "reconciliation"
                and "does not document lookup by client_order_id" in str(error)
            )
            if not unsupported_shadowfax_lookup:
                raise
            upstream = None
        if upstream:
            persisted = self.persist_booking(db, order_id, upstream)
            OrderOperationsStore.record_timeline_event(order_id, "courier_booking_reconciled", operator=operator, details={"provider": adapter.provider, "provider_order_id": upstream.provider_order_id, "awb": upstream.awb})
            return {"shipment": snapshot(persisted), "existing": True, "reconciled": True}

        upsert_shipment(
            db, order_id, provider=adapter.provider,
            # Shadowfax client_order_id is our merchant reference, not provider evidence.
            provider_order_id=None if adapter.provider == "shadowfax" else merchant_order_id,
            booking_status="booking_initiated", booking_confidence=None,
            reconciliation_status=None, latest_status="Booking request initiated",
            last_synced_at=datetime.now(timezone.utc),
        )
        OrderOperationsStore.record_timeline_event(order_id, "courier_booking_requested", operator=operator, details={"provider": adapter.provider, "merchant_order_id": merchant_order_id})
        try:
            result = await adapter.create_booking(request)
        except Exception as error:
            uncertain = not isinstance(error, ProviderError) or error.uncertain
            upsert_shipment(
                db, order_id, booking_status="booking_uncertain" if uncertain else "booking_failed",
                booking_confidence=BookingConfidence.UNCERTAIN,
                reconciliation_status=ReconciliationStatus.PENDING if uncertain else ReconciliationStatus.FAILED,
                reconciliation_error=str(error), latest_status="Provider response uncertain" if uncertain else "Booking failed",
                last_synced_at=datetime.now(timezone.utc),
            )
            OrderOperationsStore.record_timeline_event(order_id, "courier_booking_uncertain" if uncertain else "courier_booking_failed", operator=operator, details={"provider": adapter.provider, "error": str(error)})
            raise
        persisted = self.persist_booking(db, order_id, result)
        OrderOperationsStore.record_timeline_event(order_id, "courier_booked", operator=operator, details={"provider": adapter.provider, "provider_order_id": result.provider_order_id, "shipment_id": result.shipment_id, "awb": result.awb})
        return {"shipment": snapshot(persisted), "existing": result.existing}

    def persist_booking(self, db: Session, order_id: str, result: BookingResult):
        booked = result.status not in {NormalizedShipmentStatus.UNKNOWN, NormalizedShipmentStatus.CREATED} or bool(result.awb)
        persisted_booked_at = result.booked_at or (datetime.now(timezone.utc) if booked else None)
        return upsert_shipment(
            db, order_id, provider=result.provider, provider_order_id=result.provider_order_id,
            shipment_id=result.shipment_id, awb=result.awb, tracking_url=result.tracking_url,
            courier_name=result.service or result.provider.title(), courier_service=result.service,
            booking_status="booked" if booked else "pending_awb", booked_at=persisted_booked_at,
            latest_status=result.status.value, normalized_status=result.status.value,
            label_url=result.label_url, label_format=result.label_format.value if result.label_format else None,
            raw_provider_response=_json(result.raw_response), booking_confidence=result.confidence.value,
            reconciliation_status=result.reconciliation_status.value, reconciliation_error=None,
            last_synced_at=datetime.now(timezone.utc), label_print_status="not_printed" if result.awb else None,
            label_tracking_activated_at=datetime.now(timezone.utc) if result.awb else None,
        )

    async def reconcile(self, db: Session, *, order_id: str, adapter: CourierAdapter, operator: str) -> dict[str, Any]:
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.provider_order_id:
            raise ProviderError("No provider order exists to reconcile.", provider=adapter.provider, operation="reconciliation")
        result = await adapter.reconcile_booking(shipment.provider_order_id)
        if result is None:
            upsert_shipment(db, order_id, reconciliation_status=ReconciliationStatus.MANUAL_REVIEW, reconciliation_error="Provider could not confirm the booking.", last_synced_at=datetime.now(timezone.utc))
            return snapshot(get_shipment(db, order_id))
        persisted = self.persist_booking(db, order_id, result)
        OrderOperationsStore.record_timeline_event(order_id, "courier_booking_reconciled", operator=operator, details={"provider": adapter.provider, "awb": result.awb})
        return snapshot(persisted)

    async def track(self, db: Session, *, order_id: str, adapter: CourierAdapter, operator: str, tracking_audit: dict[str, Any] | None = None) -> dict[str, Any]:
        shipment = get_shipment(db, order_id)
        if shipment is None:
            raise ProviderError("Shipment not found.", provider=adapter.provider, operation="tracking")
        result = await adapter.track_shipment(snapshot(shipment))
        persisted = upsert_shipment(
            db, order_id, latest_status=result.provider_status or result.status.value,
            normalized_status=result.status.value, latest_scan=result.latest_scan,
            latest_tracking_at=result.latest_tracking_at, tracking_url=result.tracking_url or shipment.tracking_url,
            terminal_status=result.status.value if result.terminal else None,
            ndr_reason=result.ndr_reason, ndr_attempt=result.ndr_attempt, ndr_remarks=result.courier_remarks,
            raw_provider_response=_json(result.raw_response), last_synced_at=datetime.now(timezone.utc),
        )
        inserted_events = append_tracking_events(
            db, order_id=order_id, shipment=snapshot(persisted), result=result,
            source="api_poll",
            order_number=shipment.provider_order_id if adapter.provider in {"shiprocket", "delhivery"} else None,
        )
        if tracking_audit is not None:
            raw = result.raw_response if isinstance(result.raw_response, dict) else {}
            if adapter.provider == "shiprocket" and "tracking_data" in raw:
                response_format = "shiprocket_tracking_data"
            elif adapter.provider == "delhivery" and ("raw" in raw or "ShipmentData" in raw):
                response_format = "delhivery_shipment_data"
            elif adapter.provider == "shadowfax" and ("tracking_details" in raw or "provider_response" in raw):
                response_format = "shadowfax_v4_tracking"
            else:
                response_format = "normalized_current_status"
            tracking_audit.update({
                "events_returned": len(extract_tracking_events(result)),
                "new_events_persisted": len(inserted_events),
                "terminal_status_detected": result.status.value if result.terminal else None,
                "response_format": response_format,
            })
        OrderOperationsStore.record_timeline_event(order_id, "courier_tracking_updated", operator=operator, details={"provider": adapter.provider, "status": result.status.value, "scan": result.latest_scan})
        return snapshot(persisted)

    async def cancel(self, db: Session, *, order_id: str, adapter: CourierAdapter, operator: str) -> dict[str, Any]:
        shipment = get_shipment(db, order_id)
        if shipment is None:
            raise ProviderError("Shipment not found.", provider=adapter.provider, operation="cancellation")
        result = await adapter.cancel_booking(snapshot(shipment))
        if result.cancelled:
            upsert_shipment(db, order_id, booking_status="cancelled", latest_status=result.provider_status or "Cancelled", normalized_status="cancelled", terminal_status="cancelled", raw_provider_response=_json(result.raw_response), last_synced_at=datetime.now(timezone.utc))
        OrderOperationsStore.record_timeline_event(order_id, "courier_cancellation", operator=operator, details={"provider": adapter.provider, "status": result.status, "message": result.message})
        return {"result": result.model_dump(mode="json"), "shipment": snapshot(get_shipment(db, order_id))}
