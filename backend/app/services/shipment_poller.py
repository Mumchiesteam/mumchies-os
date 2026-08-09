from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.shipment_event import ShipmentEvent
from app.models.shiprocket import ShiprocketShipment
from app.repositories.shiprocket import snapshot
from app.services.courier_platform import ProviderError, courier_registry
from app.services.courier_platform.service import CourierPlatformService
from app.services.report_snapshots import ReportSnapshotStore
from app.services.shipment_events import normalize_event_status
from app.services.shipment_status import has_persisted_provider_booking_evidence, has_uncertain_provider_booking

LOGGER = logging.getLogger(__name__)
POLLER_SNAPSHOT_KEY = "shipment_tracking_poller"
TERMINAL_EVENTS = {"delivered", "rto_delivered", "cancelled"}
ENABLED_PROVIDERS = {"shiprocket", "delhivery"}
_run_lock = asyncio.Lock()


class PollTrackingError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def shadowfax_polling_enabled() -> bool:
    return bool(settings.shadowfax_tracking_poll_enabled)


def provider_polling_enabled(provider: str) -> bool:
    normalized = provider.casefold()
    return normalized in ENABLED_PROVIDERS or (normalized == "shadowfax" and shadowfax_polling_enabled())


def shipment_poll_eligible(shipment: ShiprocketShipment) -> bool:
    state = snapshot(shipment)
    provider = str(shipment.provider or "").strip().casefold()
    if not provider_polling_enabled(provider):
        return False
    if not has_persisted_provider_booking_evidence(state) or has_uncertain_provider_booking(state):
        return False
    if not str(shipment.awb or "").strip():
        return False
    if str(shipment.booking_status or "").strip().casefold() in {"booking_failed", "failed", "new", "pending"}:
        return False
    latest_lifecycle = normalize_event_status(shipment.latest_status or shipment.normalized_status)
    terminal = normalize_event_status(shipment.terminal_status)
    return latest_lifecycle not in TERMINAL_EVENTS and terminal not in TERMINAL_EVENTS


def eligible_shipments(db: Session, *, batch_size: int) -> list[ShiprocketShipment]:
    rows = db.scalars(
        select(ShiprocketShipment)
        .order_by(ShiprocketShipment.last_synced_at.asc().nulls_first(), ShiprocketShipment.order_id.asc())
    ).all()
    return [shipment for shipment in rows if shipment_poll_eligible(shipment)][:batch_size]


def _error_category(error: Exception) -> tuple[str, bool]:
    status = getattr(error, "http_status", None) or getattr(error, "status_code", None)
    if isinstance(error, httpx.TimeoutException):
        return "timeout", True
    if isinstance(error, httpx.TransportError):
        return "transport_error", True
    if status in {401, 403}:
        return "authentication", False
    if status == 404:
        return "not_found", False
    if status == 429:
        return "rate_limited", True
    if isinstance(status, int) and status >= 500:
        return "provider_5xx", True
    if isinstance(error, (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError)):
        return "malformed_response", False
    return "provider_error", bool(getattr(error, "retryable", False))


async def _track_with_limited_retry(
    db: Session, shipment: ShiprocketShipment, *, sleep: Callable[[float], Any], service: CourierPlatformService,
) -> int:
    before = db.scalar(select(func.count()).select_from(ShipmentEvent).where(ShipmentEvent.order_id == shipment.order_id)) or 0
    adapter = courier_registry.get(str(shipment.provider))
    for attempt in range(2):
        try:
            await service.track(db, order_id=shipment.order_id, adapter=adapter, operator="shipment-poller")
            after = db.scalar(select(func.count()).select_from(ShipmentEvent).where(ShipmentEvent.order_id == shipment.order_id)) or 0
            return max(0, after - before)
        except Exception as error:
            category, retryable = _error_category(error)
            if attempt == 0 and retryable:
                await sleep(2.0)
                continue
            raise PollTrackingError(category) from error
    return 0


def poller_status() -> dict[str, Any]:
    snapshot_value = ReportSnapshotStore.get(POLLER_SNAPSHOT_KEY) or {}
    data = snapshot_value.get("data") if isinstance(snapshot_value.get("data"), dict) else {}
    return {
        "enabled": bool(settings.shipment_tracking_poller_enabled),
        "interval_seconds": settings.shipment_tracking_poll_interval_seconds,
        "batch_size": settings.shipment_tracking_poll_batch_size,
        "providers": {"shiprocket": True, "delhivery": True, "shadowfax": shadowfax_polling_enabled()},
        **data,
        "snapshot_updated_at": snapshot_value.get("last_refreshed_at"),
        "snapshot_error": snapshot_value.get("refresh_error"),
    }


async def run_tracking_poll(
    session_factory, *, sleep: Callable[[float], Any] = asyncio.sleep,
    service: CourierPlatformService | None = None,
) -> dict[str, Any]:
    if _run_lock.locked():
        return {"state": "overlap_skipped", "overlap_prevented": True}
    async with _run_lock:
        started_at = datetime.now(timezone.utc).isoformat()
        stats: dict[str, Any] = {
            "state": "running", "last_poll_started": started_at, "last_poll_completed": None,
            "shipments_attempted": 0, "shipments_succeeded": 0, "shipments_failed": 0,
            "new_events_persisted": 0, "rate_limit_failures": 0, "last_error": None,
            "provider_stats": {}, "overlap_prevented": False,
        }
        ReportSnapshotStore.save_success(POLLER_SNAPSHOT_KEY, stats)
        tracking_service = service or CourierPlatformService()
        with session_factory() as db:
            shipments = eligible_shipments(db, batch_size=max(1, min(100, settings.shipment_tracking_poll_batch_size)))
            for index, shipment in enumerate(shipments):
                provider = str(shipment.provider or "unknown").casefold()
                provider_stats = stats["provider_stats"].setdefault(provider, {"attempted": 0, "succeeded": 0, "failed": 0, "new_events": 0})
                stats["shipments_attempted"] += 1
                provider_stats["attempted"] += 1
                try:
                    added = await _track_with_limited_retry(db, shipment, sleep=sleep, service=tracking_service)
                    stats["shipments_succeeded"] += 1
                    stats["new_events_persisted"] += added
                    provider_stats["succeeded"] += 1
                    provider_stats["new_events"] += added
                except Exception as error:
                    db.rollback()
                    category = error.category if isinstance(error, PollTrackingError) else "provider_error"
                    stats["shipments_failed"] += 1
                    provider_stats["failed"] += 1
                    if category == "rate_limited":
                        stats["rate_limit_failures"] += 1
                    stats["last_error"] = {
                        "provider": provider, "reference": str(shipment.awb or shipment.shipment_id or ""),
                        "category": category, "at": datetime.now(timezone.utc).isoformat(),
                    }
                    LOGGER.warning("Shipment tracking poll failed provider=%s reference=%s category=%s", provider, shipment.awb or shipment.shipment_id, category)
                if index + 1 < len(shipments):
                    await sleep(max(0.25, settings.shipment_tracking_poll_spacing_seconds))
        stats["state"] = "completed"
        stats["last_poll_completed"] = datetime.now(timezone.utc).isoformat()
        ReportSnapshotStore.save_success(POLLER_SNAPSHOT_KEY, stats)
        return stats


async def tracking_poller_loop(session_factory) -> None:
    while True:
        try:
            await run_tracking_poll(session_factory)
        except Exception as error:
            LOGGER.exception("Shipment tracking poller run failed")
            ReportSnapshotStore.save_error(POLLER_SNAPSHOT_KEY, type(error).__name__)
        await asyncio.sleep(max(300, settings.shipment_tracking_poll_interval_seconds))
