from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ndr import NDRCase, NDREvent
from app.models.shipment_event import ShipmentEvent
from app.services.courier_platform import courier_registry
from app.services.shipment_events import append_tracking_events, extract_tracking_events, normalize_event_status

LOGGER = logging.getLogger(__name__)
SUPPORTED_PROVIDERS = {"delhivery", "shiprocket", "shadowfax"}
TERMINAL_CLASSIFICATIONS = {"delivered", "rto_complete", "cancelled"}
RTO_PROGRESS = {"rto_initiated", "rto_in_transit"}
TRANSIT = {"in_transit", "out_for_delivery", "reattempt", "delivery_attempted", "picked_up"}
_run_lock = asyncio.Lock()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def provider_name(value: str | None) -> str:
    return str(value or "").strip().casefold()


def valid_tracking_identity(case: NDRCase) -> bool:
    return provider_name(case.provider) in SUPPORTED_PROVIDERS and bool(str(case.awb or "").strip())


def enroll_case(case: NDRCase, *, now: datetime | None = None) -> bool:
    """Enroll only imported/current cases; migrations intentionally do not backfill history."""
    if not valid_tracking_identity(case) or case.tracking_enrolled_at is not None:
        return False
    enrolled = now or datetime.now(timezone.utc)
    case.tracking_enrolled_at = enrolled
    case.tracking_next_attempt_at = enrolled
    case.tracking_expires_at = max(enrolled, _aware(case.first_ndr_at)) + timedelta(days=settings.ndr_tracking_expiry_days)
    case.tracking_attempt_count = 0
    case.tracking_consecutive_failures = 0
    return True


def classify_status(value: Any) -> str:
    normalized = normalize_event_status(value)
    if normalized == "delivered":
        return "delivered"
    if normalized == "rto_delivered":
        return "rto_complete"
    if normalized in RTO_PROGRESS:
        return "rto_in_progress"
    if normalized in TRANSIT:
        return "in_transit_reattempt"
    if normalized == "cancelled":
        return "cancelled"
    return "unknown"


def classify_tracking_result(result: Any) -> str:
    observations = extract_tracking_events(result)
    ranked = {"unknown": 0, "in_transit_reattempt": 1, "rto_in_progress": 2, "cancelled": 3, "rto_complete": 4, "delivered": 4}
    values = [classify_status(item.get("status") or item.get("code")) for item in observations]
    return max(values or [classify_status(result.provider_status or result.status)], key=lambda item: ranked[item])


def _exact_events(db: Session, case: NDRCase) -> list[ShipmentEvent]:
    return db.scalars(
        select(ShipmentEvent).where(
            ShipmentEvent.awb == str(case.awb).strip(),
            ShipmentEvent.provider == provider_name(case.provider),
        ).order_by(ShipmentEvent.provider_event_at.desc().nulls_last(), ShipmentEvent.recorded_at.desc())
    ).all()


def reconcile_persisted_events(db: Session, case: NDRCase) -> str:
    """Classify exact provider/AWB evidence; only completed outcomes resolve."""
    events = _exact_events(db, case)
    terminal = next((event for event in events if classify_status(event.normalized_status) in TERMINAL_CLASSIFICATIONS), None)
    evidence = terminal or (events[0] if events else None)
    classification = classify_status(evidence.normalized_status) if evidence else "unknown"
    occurred_at = (evidence.provider_event_at or evidence.recorded_at) if evidence else datetime.now(timezone.utc)
    # A conclusive terminal observation is sticky and cannot be downgraded by stale scans.
    if case.tracking_classification in TERMINAL_CLASSIFICATIONS and classification not in TERMINAL_CLASSIFICATIONS:
        return case.tracking_classification
    case.tracking_classification = classification
    case.tracking_classified_at = occurred_at
    if classification not in {"delivered", "rto_complete"}:
        return classification
    outcome = "delivered" if classification == "delivered" else "rto_confirmed"
    if case.resolution_source == "manual" and case.resolution_outcome and case.resolution_outcome != outcome:
        if not db.scalar(select(NDREvent.id).where(NDREvent.case_id == case.id, NDREvent.event_type == "provider_outcome_conflict")):
            db.add(NDREvent(id=str(uuid4()), case_id=case.id, event_type="provider_outcome_conflict", description=f"Provider later reported {outcome.replace('_', ' ').title()}; manual outcome was preserved for audit.", actor_name="Mumchies OS", event_data={"manual_outcome": case.resolution_outcome, "provider_outcome": outcome, "awb": case.awb, "provider": case.provider}))
        return classification
    if not case.resolution_outcome:
        case.current_status = "resolved"
        case.source_lifecycle = "resolved"
        case.resolved_at = occurred_at
        case.resolution_outcome = outcome
        case.resolution_source = "provider"
        case.resolved_by_name = "Mumchies OS"
        case.resolution_note = f"Resolved automatically from persisted {provider_name(case.provider)} tracking evidence."
        event_type = "delivered_resolution" if outcome == "delivered" else "terminal_shipment_resolution"
        db.add(NDREvent(id=str(uuid4()), case_id=case.id, event_type=event_type, description=f"NDR closed after {classification.replace('_', ' ')} was confirmed.", actor_name="Mumchies OS", event_data={"awb": case.awb, "provider": case.provider, "outcome": outcome, "evidence": "shipment_event"}))
    return classification


def eligible_cases(db: Session, *, now: datetime, batch_size: int) -> list[NDRCase]:
    rows = db.scalars(select(NDRCase).where(
        NDRCase.tracking_enrolled_at.is_not(None), NDRCase.current_status != "resolved",
        NDRCase.tracking_next_attempt_at.is_not(None), NDRCase.tracking_next_attempt_at <= now,
        or_(NDRCase.tracking_expires_at.is_(None), NDRCase.tracking_expires_at > now),
    ).order_by((NDRCase.source_lifecycle != "active").asc(), NDRCase.tracking_next_attempt_at.asc()).limit(batch_size)).all()
    return [case for case in rows if valid_tracking_identity(case)]


def _next_interval(case: NDRCase) -> int:
    return settings.ndr_tracking_active_interval_seconds if case.source_lifecycle == "active" else settings.ndr_tracking_inactive_interval_seconds


async def poll_case(db: Session, case: NDRCase, *, now: datetime | None = None) -> str:
    attempted = now or datetime.now(timezone.utc)
    case.tracking_last_attempted_at = attempted
    case.tracking_attempt_count = int(case.tracking_attempt_count or 0) + 1
    try:
        adapter = courier_registry.get(provider_name(case.provider))
        result = await adapter.track_shipment({"provider": provider_name(case.provider), "awb": str(case.awb).strip(), "order_id": case.order_id, "order_number": case.order_number})
        if provider_name(result.provider) != provider_name(case.provider):
            raise ValueError("Tracking adapter returned a mismatched provider identity.")
        # append_tracking_events commits before reconciliation by design.
        append_tracking_events(db, order_id=case.order_id or f"ndr:{case.id}", order_number=case.order_number, shipment={"provider": provider_name(case.provider), "awb": str(case.awb).strip()}, result=result, source="ndr_poll")
        case = db.get(NDRCase, case.id)
        classification = reconcile_persisted_events(db, case)
        case.tracking_last_result = "success"
        case.tracking_consecutive_failures = 0
        case.tracking_next_attempt_at = None if classification in TERMINAL_CLASSIFICATIONS else attempted + timedelta(seconds=_next_interval(case))
        db.commit()
        return classification
    except Exception as error:
        db.rollback()
        case = db.get(NDRCase, case.id)
        case.tracking_last_attempted_at = attempted
        case.tracking_attempt_count = int(case.tracking_attempt_count or 0) + 1
        case.tracking_consecutive_failures = int(case.tracking_consecutive_failures or 0) + 1
        status = getattr(error, "http_status", None) or getattr(error, "status_code", None)
        case.tracking_last_result = "not_found" if status == 404 else "provider_error"
        backoff = min(43200, _next_interval(case) * (2 ** min(case.tracking_consecutive_failures - 1, 3)))
        case.tracking_next_attempt_at = attempted + timedelta(seconds=backoff)
        db.commit()
        LOGGER.warning("NDR tracking failed provider=%s case=%s result=%s", provider_name(case.provider), case.id, case.tracking_last_result)
        return case.tracking_last_result


async def run_ndr_tracking_poll(session_factory, *, sleep: Callable[[float], Any] = asyncio.sleep) -> dict[str, int]:
    if _run_lock.locked():
        return {"attempted": 0, "skipped_overlap": 1}
    async with _run_lock:
        with session_factory() as db:
            cases = eligible_cases(db, now=datetime.now(timezone.utc), batch_size=settings.ndr_tracking_poll_batch_size)
            counts: dict[str, int] = {"attempted": 0}
            for index, case in enumerate(cases):
                result = await poll_case(db, case)
                counts["attempted"] += 1
                counts[result] = counts.get(result, 0) + 1
                if index + 1 < len(cases):
                    await sleep(max(.25, settings.ndr_tracking_poll_spacing_seconds))
            return counts


async def ndr_tracking_poller_loop(session_factory) -> None:
    while True:
        try:
            await run_ndr_tracking_poll(session_factory)
        except Exception:
            LOGGER.exception("NDR tracking poller run failed")
        await asyncio.sleep(max(300, settings.ndr_tracking_poll_interval_seconds))
