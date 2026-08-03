from types import SimpleNamespace

from app.api.routes.orders import _call_outcome_is_on_hold, _call_outcome_requires_follow_up, _matches_queue
from app.services.shipment_status import derive_operational_status, has_persisted_provider_booking_evidence


def order(latest: str, attempts: int = 1):
    return SimpleNamespace(
        payment_type="cod", latest_call_result=latest, call_attempt_count=attempts,
        human_action_count=attempts, shipment=None, courier_sync_error=None,
        courier_sync_status=None, address_sync_results=None, cancelled_at=None,
        shopify_status=None, fulfillment_status=None, tags=[], payment_status="pending", external_tracking=None, operational_status=None,
    )


def test_on_hold_routes_only_to_on_hold_previous_view():
    held = order("On Hold")
    assert _call_outcome_is_on_hold(held)
    assert not _call_outcome_requires_follow_up(held)
    assert _matches_queue(held, "previous", __import__('datetime').datetime.now(), "on_hold")
    assert not _matches_queue(held, "previous", __import__('datetime').datetime.now(), "follow_up")


def test_latest_outcome_moves_order_out_of_on_hold():
    held = order("On Hold")
    held.latest_call_result = "Busy"
    assert not _call_outcome_is_on_hold(held)
    assert _call_outcome_requires_follow_up(held)


def test_on_hold_is_not_booking_ready_and_manual_shadowfax_evidence_is_canonical():
    held = order("On Hold")
    assert derive_operational_status(held, {"call_logs": [{"result": "On Hold"}]}, None) == "On Hold"
    assert has_persisted_provider_booking_evidence({"provider": "shadowfax", "provider_order_id": "SFX-1", "booking_status": "booked"})
    assert not has_persisted_provider_booking_evidence({"provider": "shadowfax", "provider_order_id": "SFX-1", "booking_status": "new"})
