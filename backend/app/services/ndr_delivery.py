from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.ndr import NDRCase, NDREvent
from app.models.shiprocket import ShiprocketShipment


def _terminal_outcome(shipment: ShiprocketShipment) -> str | None:
    values = {str(value or "").strip().casefold().replace("-", " ").replace("_", " ") for value in (shipment.normalized_status, shipment.terminal_status, shipment.latest_status)}
    if "delivered" in values: return "delivered"
    if values & {"rto delivered", "return delivered"}: return "rto_delivered"
    if values & {"rto in transit", "return in transit", "rto initiated", "return initiated", "rto"}: return "rto_underway"
    if values & {"cancelled", "canceled"}: return "cancelled"
    return None


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
    if shipment is None or outcome is None:
        return False
    if case.current_status == "resolved" and case.source_lifecycle == "resolved":
        return True
    resolved_at = now or datetime.now(timezone.utc)
    case.current_status = "resolved"
    case.source_lifecycle = "resolved"
    case.resolved_at = case.resolved_at or resolved_at
    label = outcome.replace("_", " ").title()
    case.resolution_note = case.resolution_note or f"Resolved automatically after canonical shipment outcome {label} was confirmed."
    event_type = "delivered_resolution" if outcome == "delivered" else "terminal_shipment_resolution"
    db.add(NDREvent(id=str(uuid4()), case_id=case.id, event_type=event_type, description=f"NDR closed after canonical shipment outcome {label} was confirmed.", actor_name="Mumchies OS", event_data={"shipment_order_id": shipment.order_id, "awb": shipment.awb, "outcome": outcome}))
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
