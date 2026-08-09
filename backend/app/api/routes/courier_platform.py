from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.courier_platform import courier_registry
from app.services.shipment_events import shipment_event_history

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
