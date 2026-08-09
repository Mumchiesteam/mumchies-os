from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.courier_platform import courier_registry
from app.services.shipment_events import shipment_event_history
from app.services.shipment_poller import poller_audit_status, poller_status

router = APIRouter(prefix="/couriers", tags=["courier-platform"])


@router.get("/providers")
async def courier_providers() -> dict[str, dict[str, object]]:
    """Public-to-operators capability metadata; never returns provider credentials."""
    return courier_registry.capabilities()


@router.get("/orders/{order_id}/events")
async def courier_shipment_events(order_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    """Read-only provider-neutral shipment lifecycle history."""
    events = shipment_event_history(db, order_id)
    return {"order_id": order_id, "events": events, "total": len(events)}


@router.get("/poller/status")
async def courier_poller_status(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    user = getattr(request.state, "auth_user", None)
    if user is None or user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return {**poller_status(), "audit": poller_audit_status(db)}
