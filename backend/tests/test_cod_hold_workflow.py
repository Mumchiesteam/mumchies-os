from types import SimpleNamespace
import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes.orders import CallLogPayload, _call_outcome_is_on_hold, _call_outcome_requires_follow_up, _matches_queue, add_call_log, record_cod_whatsapp_opened
from app.services.order_operations import OrderOperationsStore
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


def test_on_hold_requires_three_non_space_characters(monkeypatch):
    request = Request({"type": "http", "headers": []})
    monkeypatch.setattr(OrderOperationsStore, "append_call_log", lambda *_: pytest.fail("invalid note must not persist"))
    with pytest.raises(HTTPException, match="Add a reason") as error:
        asyncio.run(add_call_log("1", CallLogPayload(result="On Hold", comment=" x "), request))
    assert error.value.status_code == 422


def test_whatsapp_audit_is_operator_specific_and_does_not_add_attempt(monkeypatch):
    request = Request({"type": "http", "headers": []})
    original = {"call_logs": [{"result": "No Answer", "operator": "Caller", "timestamp": "2026-08-08T10:00:00Z"}]}
    recorded = {}
    monkeypatch.setattr("app.api.routes.orders.current_actor", lambda _request: "Operator One")
    monkeypatch.setattr(OrderOperationsStore, "get", lambda _order_id: original)
    def record(order_id, action, *, operator=None, **_kwargs):
        recorded.update(order_id=order_id, action=action, operator=operator)
        return {**original, "timeline_events": [recorded.copy()]}
    monkeypatch.setattr(OrderOperationsStore, "record_timeline_event", record)
    result = asyncio.run(record_cod_whatsapp_opened("1", request))
    assert recorded["action"] == "WhatsApp opened for COD confirmation"
    assert recorded["operator"]
    assert len(result["call_logs"]) == 1


@pytest.mark.parametrize("result", ["Confirmed", "On Hold", "Cancelled"])
def test_whatsapp_audit_rejects_non_follow_up_outcomes(monkeypatch, result):
    request = Request({"type": "http", "headers": []})
    monkeypatch.setattr(OrderOperationsStore, "get", lambda _order_id: {"call_logs": [{"result": result}]})
    with pytest.raises(HTTPException) as error:
        asyncio.run(record_cod_whatsapp_opened("1", request))
    assert error.value.status_code == 409


def test_on_hold_is_not_booking_ready_and_manual_shadowfax_evidence_is_canonical():
    held = order("On Hold")
    assert derive_operational_status(held, {"call_logs": [{"result": "On Hold"}]}, None) == "On Hold"
    assert has_persisted_provider_booking_evidence({"provider": "shadowfax", "provider_order_id": "SFX-1", "booking_status": "booked"})
    assert not has_persisted_provider_booking_evidence({"provider": "shadowfax", "provider_order_id": "SFX-1", "booking_status": "new"})
