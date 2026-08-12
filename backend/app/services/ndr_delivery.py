from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.ndr import NDRCase, NDREvent
from app.models.shiprocket import ShiprocketShipment
from app.models.shipment_event import ShipmentEvent
from app.services.shipment_events import normalize_event_status


def _terminal_outcome(shipment: ShiprocketShipment) -> str | None:
    values = {normalize_event_status(value) for value in (shipment.normalized_status, shipment.terminal_status, shipment.latest_status)}
    if "rto_delivered" in values: return "rto_delivered"
    if values & {"rto_in_transit", "rto_initiated"}: return "rto_underway"
    if "delivered" in values: return "delivered"
    if "cancelled" in values: return "cancelled"
    return None


def _event_terminal_outcome(db: Session, case: NDRCase) -> tuple[str | None, ShipmentEvent | None]:
    awb = str(case.awb or "").strip(); order_number = str(case.order_number or case.order_id or "").strip().lstrip("#")
    # An AWB is authoritative. Only fall back to the visible order number when
    # the NDR source supplied no AWB; never blend unrelated order/AWB histories.
    predicates = [ShipmentEvent.awb == awb] if awb else ([ShipmentEvent.order_number == order_number] if order_number else [])
    if not predicates: return None, None
    terminal = {"delivered":"delivered", "rto_initiated":"rto_underway", "rto_in_transit":"rto_underway", "rto_delivered":"rto_delivered", "cancelled":"cancelled"}
    events = db.scalars(select(ShipmentEvent).where(or_(*predicates)).order_by(ShipmentEvent.provider_event_at.desc(), ShipmentEvent.recorded_at.desc())).all()
    event = next((value for value in events if normalize_event_status(value.normalized_status) in terminal), None)
    normalized = normalize_event_status(event.normalized_status) if event else None
    return (terminal.get(normalized), event) if event else (None, None)


def canonical_shipment_for_case(db: Session, case: NDRCase) -> ShiprocketShipment | None:
    awb = str(case.awb or "").strip()
    order_number = str(case.order_number or case.order_id or "").strip().lstrip("#")
    predicates = []
    if awb:
        predicates.extend((ShiprocketShipment.awb == awb, ShiprocketShipment.shopify_tracking_number == awb))
    if order_number:
        predicates.extend((ShiprocketShipment.provider_order_id == order_number, ShiprocketShipment.order_id == order_number))
    if not predicates:
        return None
    candidates = db.scalars(select(ShiprocketShipment).where(or_(*predicates))).all()
    exact_awb = next((shipment for shipment in candidates if awb and awb in {shipment.awb, shipment.shopify_tracking_number}), None)
    return exact_awb or (candidates[0] if len(candidates) == 1 else None)


def resolve_if_canonically_terminal(db: Session, case: NDRCase, *, now: datetime | None = None) -> bool:
    shipment = canonical_shipment_for_case(db, case)
    outcome = _terminal_outcome(shipment) if shipment else None
    event = None
    if outcome is None: outcome, event = _event_terminal_outcome(db, case)
    if outcome is None:
        return False
    provider_outcome = "delivered" if outcome == "delivered" else "rto_confirmed" if outcome in {"rto_underway", "rto_delivered"} else None
    if case.resolution_source == "manual" and case.resolution_outcome and provider_outcome and case.resolution_outcome != provider_outcome:
        already = db.scalar(select(NDREvent.id).where(NDREvent.case_id == case.id, NDREvent.event_type == "provider_outcome_conflict"))
        if not already:
            db.add(NDREvent(id=str(uuid4()), case_id=case.id, event_type="provider_outcome_conflict", description=f"Provider later reported {provider_outcome.replace('_', ' ').title()}; manual outcome was preserved for audit.", actor_name="Mumchies OS", event_data={"manual_outcome": case.resolution_outcome, "provider_outcome": provider_outcome}))
        return True
    if case.current_status == "resolved" and case.source_lifecycle == "resolved" and case.resolution_outcome:
        return True
    resolved_at = now or datetime.now(timezone.utc)
    case.current_status = "resolved"
    case.source_lifecycle = "resolved"
    case.resolved_at = case.resolved_at or resolved_at
    case.resolution_outcome = case.resolution_outcome or provider_outcome
    case.resolution_source = case.resolution_source or "provider"
    case.resolved_by_name = case.resolved_by_name or "Mumchies OS"
    label = outcome.replace("_", " ").title()
    case.resolution_note = case.resolution_note or f"Resolved automatically after canonical shipment outcome {label} was confirmed."
    event_type = "delivered_resolution" if outcome == "delivered" else "terminal_shipment_resolution"
    existing = db.scalar(select(NDREvent.id).where(NDREvent.case_id == case.id, NDREvent.event_type == event_type))
    if not existing:
        db.add(NDREvent(id=str(uuid4()), case_id=case.id, event_type=event_type, description=f"NDR closed after canonical shipment outcome {label} was confirmed.", actor_name="Mumchies OS", event_data={"shipment_order_id": shipment.order_id if shipment else event.order_id, "awb": shipment.awb if shipment else event.awb, "outcome": case.resolution_outcome, "source": "provider", "evidence": "shipment_row" if shipment and _terminal_outcome(shipment) else "shipment_event"}))
    return True


def resolve_active_terminal_cases(db: Session) -> int:
    resolved = 0
    for case in db.scalars(select(NDRCase).where(NDRCase.source_lifecycle == "active", NDRCase.current_status != "resolved")).all():
        if resolve_if_canonically_terminal(db, case):
            resolved += 1
    if resolved:
        db.commit()
    return resolved

# Compatibility aliases for callers/tests deployed with the delivered-only rule.
resolve_if_canonically_delivered = resolve_if_canonically_terminal
resolve_active_delivered_cases = resolve_active_terminal_cases
