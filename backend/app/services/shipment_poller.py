from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.shipment_event import ShipmentEvent
from app.models.shipment_poll import ShipmentPollAttempt, ShipmentPollRun
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
    def __init__(self, category: str, *, http_status: int | None, summary: str) -> None:
        super().__init__(category)
        self.category = category
        self.http_status = http_status
        self.summary = summary


def _safe_error_summary(error: Exception) -> str:
    value = f"{type(error).__name__}: {str(error)}"
    value = re.sub(r"(?i)(authorization|bearer|token|api[_-]?key|password)\s*[:=]?\s*[^\s,;]+", r"\1=[REDACTED]", value)
    value = re.sub(r"(?i)(customer[_ ]?name|phone|mobile|email|address)\s*[:=]\s*[^,;]+", r"\1=[REDACTED]", value)
    value = re.sub(r"\b[6-9]\d{9,11}\b", "[REDACTED_PHONE]", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", value)
    return value[:500]


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


def resolve_visible_order_number(order_id: str, canonical_order_numbers: dict[str, str] | None) -> str | None:
    """Resolve only from an explicit canonical Shopify mapping; provider identifiers are never fallbacks."""
    value = (canonical_order_numbers or {}).get(order_id)
    return str(value).strip() if value is not None and str(value).strip() else None


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
) -> dict[str, Any]:
    before = db.scalar(select(func.count()).select_from(ShipmentEvent).where(ShipmentEvent.order_id == shipment.order_id)) or 0
    adapter = courier_registry.get(str(shipment.provider))
    for attempt in range(2):
        try:
            audit: dict[str, Any] = {}
            await service.track(db, order_id=shipment.order_id, adapter=adapter, operator="shipment-poller", tracking_audit=audit)
            after = db.scalar(select(func.count()).select_from(ShipmentEvent).where(ShipmentEvent.order_id == shipment.order_id)) or 0
            audit["new_events_persisted"] = max(0, after - before)
            return audit
        except Exception as error:
            category, retryable = _error_category(error)
            if attempt == 0 and retryable:
                await sleep(2.0)
                continue
            status = getattr(error, "http_status", None) or getattr(error, "status_code", None)
            raise PollTrackingError(category, http_status=status if isinstance(status, int) else None, summary=_safe_error_summary(error)) from error
    return {}


def cleanup_poller_audit(db: Session, *, now: datetime | None = None, max_runs: int = 100, retention_days: int = 30) -> None:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    expired = set(db.scalars(select(ShipmentPollRun.run_id).where(ShipmentPollRun.completed_at.is_not(None), ShipmentPollRun.completed_at < cutoff)).all())
    overflow = set(db.scalars(select(ShipmentPollRun.run_id).order_by(ShipmentPollRun.started_at.desc()).offset(max_runs)).all())
    removed = expired | overflow
    if removed:
        db.execute(delete(ShipmentPollAttempt).where(ShipmentPollAttempt.run_id.in_(removed)))
        db.execute(delete(ShipmentPollRun).where(ShipmentPollRun.run_id.in_(removed)))
        db.commit()


def _run_dict(run: ShipmentPollRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id, "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "total_attempted": run.total_attempted, "total_succeeded": run.total_succeeded,
        "total_failed": run.total_failed, "new_events_persisted": run.new_events_persisted,
        "provider_counts": run.provider_counts or {}, "status": run.status,
    }


def poller_audit_status(db: Session, *, run_limit: int = 10, failure_limit: int = 100) -> dict[str, Any]:
    runs = db.scalars(select(ShipmentPollRun).order_by(ShipmentPollRun.started_at.desc()).limit(run_limit)).all()
    failures = db.scalars(select(ShipmentPollAttempt).where(ShipmentPollAttempt.result == "failure").order_by(ShipmentPollAttempt.attempted_at.desc()).limit(failure_limit)).all()
    provider_coverage: dict[str, dict[str, Any]] = {}
    for provider in sorted({row.provider for row in db.scalars(select(ShipmentPollAttempt)).all()}):
        attempts = db.scalars(select(ShipmentPollAttempt).where(ShipmentPollAttempt.provider == provider)).all()
        succeeded = sum(item.result == "success" for item in attempts)
        failed = sum(item.result == "failure" for item in attempts)
        provider_coverage[provider] = {"attempted": len(attempts), "succeeded": succeeded, "failed": failed, "success_percent": round(succeeded * 100 / len(attempts), 1) if attempts else 0.0}
    failure_breakdown = dict(db.execute(select(ShipmentPollAttempt.error_category, func.count()).where(ShipmentPollAttempt.result == "failure").group_by(ShipmentPollAttempt.error_category)).all())
    event_counts = dict(db.execute(select(ShipmentEvent.provider, func.count()).group_by(ShipmentEvent.provider)).all())
    timestamped_events = dict(db.execute(select(ShipmentEvent.provider, func.count()).where(ShipmentEvent.provider_event_at.is_not(None)).group_by(ShipmentEvent.provider)).all())
    lifecycle_rows = db.execute(select(ShipmentEvent.provider, ShipmentEvent.normalized_status, func.count()).group_by(ShipmentEvent.provider, ShipmentEvent.normalized_status)).all()
    lifecycle: dict[str, dict[str, int]] = {}
    for provider, status, count in lifecycle_rows:
        lifecycle.setdefault(provider, {})[status] = count
    return {
        "latest_runs": [_run_dict(run) for run in runs], "provider_coverage": provider_coverage,
        "failure_breakdown": failure_breakdown, "event_count_by_provider": event_counts,
        "provider_timestamped_events": timestamped_events, "lifecycle_coverage": lifecycle,
        "failed_shipments": [{
            "run_id": item.run_id, "order_id": item.order_id, "order_number": item.order_number,
            "provider": item.provider, "courier_service": item.courier_service,
            "awb_reference": item.awb_reference, "attempted_at": item.attempted_at.isoformat(),
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "error_category": item.error_category, "http_status": item.http_status,
            "error_summary": item.error_summary, "duration_ms": item.duration_ms,
        } for item in failures],
    }


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
    canonical_order_numbers: dict[str, str] | None = None,
) -> dict[str, Any]:
    if _run_lock.locked():
        return {"state": "overlap_skipped", "overlap_prevented": True}
    async with _run_lock:
        run_id = uuid4().hex
        started = datetime.now(timezone.utc)
        started_at = started.isoformat()
        stats: dict[str, Any] = {
            "run_id": run_id, "state": "running", "last_poll_started": started_at, "last_poll_completed": None,
            "shipments_attempted": 0, "shipments_succeeded": 0, "shipments_failed": 0,
            "new_events_persisted": 0, "rate_limit_failures": 0, "last_error": None,
            "provider_stats": {}, "overlap_prevented": False,
        }
        ReportSnapshotStore.save_success(POLLER_SNAPSHOT_KEY, stats)
        tracking_service = service or CourierPlatformService()
        with session_factory() as db:
            cleanup_poller_audit(db)
            persisted_run = ShipmentPollRun(
                run_id=run_id, started_at=started, completed_at=None, total_attempted=0,
                total_succeeded=0, total_failed=0, new_events_persisted=0,
                provider_counts={}, status="running",
            )
            db.add(persisted_run)
            db.commit()
            shipments = eligible_shipments(db, batch_size=max(1, min(100, settings.shipment_tracking_poll_batch_size)))
            for index, shipment in enumerate(shipments):
                provider = str(shipment.provider or "unknown").casefold()
                provider_stats = stats["provider_stats"].setdefault(provider, {"attempted": 0, "succeeded": 0, "failed": 0, "new_events": 0})
                stats["shipments_attempted"] += 1
                provider_stats["attempted"] += 1
                attempted_at = datetime.now(timezone.utc)
                timer = time.perf_counter()
                attempt_row = ShipmentPollAttempt(
                    id=uuid4().hex, run_id=run_id, order_id=shipment.order_id,
                    order_number=resolve_visible_order_number(shipment.order_id, canonical_order_numbers),
                    provider=provider,
                    courier_service=str(shipment.courier_service or shipment.courier_name or "").strip() or None,
                    awb_reference=str(shipment.awb or shipment.shipment_id or shipment.provider_order_id or "").strip() or None,
                    attempted_at=attempted_at, completed_at=None, result="running",
                    events_returned=0, new_events_persisted=0,
                )
                db.add(attempt_row)
                persisted_run.total_attempted += 1
                persisted_run.provider_counts = dict(stats["provider_stats"])
                db.commit()
                try:
                    audit = await _track_with_limited_retry(db, shipment, sleep=sleep, service=tracking_service)
                    added = int(audit.get("new_events_persisted") or 0)
                    stats["shipments_succeeded"] += 1
                    stats["new_events_persisted"] += added
                    provider_stats["succeeded"] += 1
                    provider_stats["new_events"] += added
                    attempt_row.result = "success"
                    attempt_row.events_returned = int(audit.get("events_returned") or 0)
                    attempt_row.new_events_persisted = added
                    attempt_row.terminal_status_detected = audit.get("terminal_status_detected")
                    attempt_row.response_format = audit.get("response_format")
                    persisted_run.total_succeeded += 1
                    persisted_run.new_events_persisted += added
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
                    attempt_row = db.get(ShipmentPollAttempt, attempt_row.id)
                    persisted_run = db.get(ShipmentPollRun, run_id)
                    attempt_row.result = "failure"
                    attempt_row.error_category = category
                    attempt_row.http_status = error.http_status if isinstance(error, PollTrackingError) else None
                    attempt_row.error_summary = error.summary if isinstance(error, PollTrackingError) else _safe_error_summary(error)
                    persisted_run.total_failed += 1
                    LOGGER.warning("Shipment tracking poll failed provider=%s reference=%s category=%s", provider, shipment.awb or shipment.shipment_id, category)
                attempt_row.completed_at = datetime.now(timezone.utc)
                attempt_row.duration_ms = round((time.perf_counter() - timer) * 1000, 2)
                persisted_run.provider_counts = dict(stats["provider_stats"])
                db.commit()
                if index + 1 < len(shipments):
                    await sleep(max(0.25, settings.shipment_tracking_poll_spacing_seconds))
            completed_at = datetime.now(timezone.utc)
            persisted_run = db.get(ShipmentPollRun, run_id)
            persisted_run.completed_at = completed_at
            persisted_run.status = "completed"
            persisted_run.provider_counts = dict(stats["provider_stats"])
            db.commit()
            cleanup_poller_audit(db)
        stats["state"] = "completed"
        stats["last_poll_completed"] = completed_at.isoformat()
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
