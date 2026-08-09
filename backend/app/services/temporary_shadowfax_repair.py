from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories.shiprocket import get_shipment
from app.services.order_operations import OrderOperationsStore


ORDER_ID = "6854925713486"
STALE_CLIENT_ORDER_ID = "324541"


def repair_legacy_shadowfax_test_324541(db: Session) -> dict[str, bool]:
    """One-time exact-match repair; never contacts Shopify or a courier provider."""
    shipment = get_shipment(db, ORDER_ID)
    if shipment is None:
        return {"provider_order_id_cleared": False, "test_state_reset": False}

    fixed_shape = (
        str(shipment.provider or "").casefold() == "shadowfax"
        and shipment.shipment_id is None
        and shipment.awb is None
        and str(shipment.booking_status or "").casefold() == "booking_failed"
        and shipment.booked_at is None
    )
    cleared = False
    if fixed_shape and shipment.provider_order_id == STALE_CLIENT_ORDER_ID:
        shipment.provider_order_id = None
        db.commit()
        cleared = True

    operations = OrderOperationsStore.get(ORDER_ID)
    legacy_guard = any(
        event.get("action") == "shadowfax_direct_test_324541_started"
        for event in operations.get("timeline_events", [])
    )
    diagnostic = operations.get("shadowfax_direct_test")
    no_returned_booking = not isinstance(diagnostic, dict) or (
        not diagnostic.get("returned_provider_id") and not diagnostic.get("returned_awb")
    )
    known_failed_test = not isinstance(diagnostic, dict) or (
        diagnostic.get("final_test_state") == "legacy_attempt_observed_without_diagnostics"
        or (
            diagnostic.get("create_result") == "provider_rejected"
            and "client_name" in str(diagnostic.get("sanitized_provider_error") or "")
        )
    )
    reset = fixed_shape and shipment.provider_order_id is None and legacy_guard and no_returned_booking and known_failed_test
    if reset:
        OrderOperationsStore.reset_legacy_shadowfax_direct_test(ORDER_ID)
    return {"provider_order_id_cleared": cleared, "test_state_reset": reset}
