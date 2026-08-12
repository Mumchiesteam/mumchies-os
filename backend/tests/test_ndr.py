from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.ndr import NDRAction, NDRImportPayload, case_action, import_cases, list_cases, resolution_analytics, summary
from app.core.config import settings
from app.db.base import Base
from app.models.ndr import NDRCase, NDREvent, NDRImportRun
from app.models.shiprocket import ShiprocketShipment
from app.models.shipment_event import ShipmentEvent
from app.models.order_read_model import OrderReadModel
from app.models.user import User
from app.services.ndr_import import import_ndr


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ndr.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def payload(run_id: str, *, rows: list[dict] | None = None, shadowfax_status: str = "success") -> NDRImportPayload:
    return NDRImportPayload.model_validate({
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": "2026-07-28T06:00:00Z",
        "source_health": {
            "shiprocket": {"status": "success"},
            "shadowfax": {"status": shadowfax_status},
        },
        "source_counts": {"shiprocket": 1, "shadowfax": 0},
        "rows": rows if rows is not None else [{
            "source": "shiprocket",
            "order_id": "323500",
            "awb": "SR123",
            "customer_name": "Customer",
            "phone": "919999999999",
            "city": "Pune",
            "status": "NDR",
            "failure_reason": "Customer unavailable",
            "attempts": 2,
            "last_update": "2026-07-28T05:00:00Z",
            "recommended_action": "Call customer",
            "whatsapp_message": "Reason-aware message",
            "whatsapp_url": "https://wa.me/919999999999?text=Reason-aware%20message",
        }],
    })


def test_import_is_idempotent_and_preserves_manual_workflow(db):
    owner = User(username="owner", display_name="Ajit", password_hash="unused", role="owner", is_active=True)
    db.add(owner)
    db.commit()
    db.refresh(owner)

    first = import_ndr(db, payload("run-1"))
    assert first.created == 1
    case = db.scalar(select(NDRCase).where(NDRCase.source_identity == "awb:SR123"))
    assert case.whatsapp_message == "Reason-aware message"

    request = SimpleNamespace(state=SimpleNamespace(auth_user=owner))
    case_action(case.id, NDRAction(action="resolve", resolution_outcome="delivered", note="Keep closed"), request, db)
    repeated = import_ndr(db, payload("run-1"))
    assert repeated.id == first.id
    assert len(db.scalars(select(NDRImportRun)).all()) == 1

    refreshed = import_ndr(db, payload("run-2"))
    db.refresh(case)
    assert refreshed.updated == 0
    assert case.current_status == "resolved"
    assert case.resolution_note == "Keep closed"
    assert case.source_lifecycle == "resolved"
    assert len(db.scalars(select(NDREvent).where(NDREvent.case_id == case.id)).all()) >= 2


@pytest.mark.parametrize("outcome", ["delivered", "rto_confirmed"])
def test_manual_resolution_outcomes_are_audited(outcome, db):
    now=datetime.now(timezone.utc);owner=User(username="operator",display_name="Operator",password_hash="unused",role="operator",is_active=True);case=NDRCase(id=outcome,source_identity=f"awb:{outcome}",awb=outcome,provider="shadowfax",order_number="323027",source_lifecycle="active",current_status="new",priority="medium",delivery_attempts=1,first_ndr_at=now-timedelta(hours=5),last_synced_at=now,products=[],cod_amount=0)
    db.add_all([owner,case,NDREvent(id=f"history-{outcome}",case_id=case.id,event_type="customer_contacted",description="Preserved",actor_name="Operator")]);db.commit();db.refresh(owner)
    case_action(case.id,NDRAction(action="resolve",resolution_outcome=outcome,note="Confirmed"),SimpleNamespace(state=SimpleNamespace(auth_user=owner)),db)
    db.refresh(case);assert (case.resolution_outcome,case.resolution_source,case.resolved_by_name)==(outcome,"manual","Operator")
    assert db.scalar(select(NDREvent).where(NDREvent.id==f"history-{outcome}")) is not None


def test_resolution_analytics_excludes_open_and_breaks_down_courier_and_reason(db):
    now=datetime.now(timezone.utc)
    def case(id,outcome,provider,reason,resolved=True): return NDRCase(id=id,source_identity=f"awb:{id}",awb=id,provider=provider,order_number=id,source_lifecycle="resolved" if resolved else "active",current_status="resolved" if resolved else "new",priority="medium",delivery_attempts=1,first_ndr_at=now-timedelta(days=2),last_synced_at=now,resolved_at=now if resolved else None,resolution_outcome=outcome,resolution_source="provider" if outcome else None,failure_reason=reason,products=[],cod_amount=0)
    db.add_all([case("d","delivered","shadowfax","Unavailable"),case("r","rto_confirmed","shadowfax","Unavailable"),case("open",None,"delhivery","Address",False)]);db.commit()
    result=resolution_analytics(period="30d",db=db)
    assert (result["delivered"],result["rto_confirmed"],result["resolution_percent"],result["open_cases"])==(1,1,50.0,1)
    shadowfax=next(row for row in result["by_courier"] if row["provider"]=="shadowfax");assert shadowfax["resolution_percent"]==50.0
    unavailable=next(row for row in result["by_failure_reason"] if row["failure_reason"]=="Unavailable");assert unavailable["resolved_cases"]==2


def test_missing_awb_uses_source_order_identity_and_failed_source_keeps_lifecycle(db):
    missing_awb = [{
        "source": "shadowfax", "order_id": "#323501", "awb": "", "status": "NDR",
        "failure_reason": "Not delivered", "attempts": 1,
    }]
    import_ndr(db, payload("run-a", rows=missing_awb))
    case = db.scalar(select(NDRCase).where(NDRCase.source_identity == "fallback:shadowfax:323501"))
    assert case is not None and case.awb is None

    import_ndr(db, payload("run-b", rows=[], shadowfax_status="failed"))
    db.refresh(case)
    assert case.source_lifecycle == "active"

    import_ndr(db, payload("run-c", rows=[], shadowfax_status="success"))
    db.refresh(case)
    assert case.source_lifecycle == "no_longer_reported"


def test_schema_version_must_be_one():
    data = payload("valid").model_dump()
    data["schema_version"] = 2
    with pytest.raises(ValueError, match="schema_version must be 1"):
        NDRImportPayload.model_validate(data)


def test_import_requires_constant_time_bearer_authentication(db, monkeypatch):
    monkeypatch.setattr(settings, "ndr_ingest_token", "configured-token")
    request = SimpleNamespace(headers={"Authorization": "Bearer wrong-token"})
    with pytest.raises(HTTPException) as error:
        import_cases(payload("unauthorized"), request, db)
    assert error.value.status_code == 401
    assert db.scalar(select(NDRImportRun)) is None

    request.headers["Authorization"] = "Bearer configured-token"
    result = import_cases(payload("authorized"), request, db)
    assert result["run_id"] == "authorized"
    assert result["created"] == 1


def test_summary_health_comes_from_latest_successful_run(db):
    successful_payload = payload("successful")
    successful_payload.source_health["shopify"] = {"status": "success", "source": "api", "phones_matched": 1, "phones_total": 1}
    import_ndr(db, successful_payload)
    failed_payload = payload("failed", rows=[], shadowfax_status="failed")
    failed_payload.source_health["shiprocket"] = {"status": "failed"}
    failed_payload.source_health["warnings"] = ["GDrive Shopify CSV is old"]
    import_ndr(db, failed_payload)
    result = summary(db)
    assert result["last_import_run_id"] == "successful"
    assert result["source_health"]["shopify"]["source"] == "api"
    assert result["source_health"].get("warnings") is None


def test_kpi_filters_apply_server_side_and_combine_with_search(db):
    now = datetime.now(timezone.utc)
    rows = [
        NDRCase(id="active", source_identity="awb:A", awb="A", provider="shiprocket", order_number="323500", source_lifecycle="active", current_status="new", priority="high", delivery_attempts=1, first_ndr_at=now, last_synced_at=now, products=[], cod_amount=0),
        NDRCase(id="awaiting", source_identity="awb:B", awb="B", provider="shadowfax", order_number="323501", source_lifecycle="active", current_status="awaiting_customer", priority="medium", delivery_attempts=1, first_ndr_at=now, last_synced_at=now, products=[], cod_amount=0),
        NDRCase(id="resolved", source_identity="awb:C", awb="C", provider="delhivery", order_number="323502", source_lifecycle="resolved", current_status="resolved", resolved_at=now, priority="low", delivery_attempts=1, first_ndr_at=now, last_synced_at=now, products=[], cod_amount=0),
        NDRCase(id="courier", source_identity="awb:D", awb="D", provider="delhivery", order_number="323503", source_lifecycle="active", current_status="courier_pending", priority="medium", delivery_attempts=1, first_ndr_at=now-timedelta(hours=80), last_synced_at=now, products=[], cod_amount=0),
    ]
    db.add_all(rows); db.commit()
    assert {item["id"] for item in list_cases(page=1, page_size=50, db=db)["items"]} == {"active", "awaiting", "courier"}
    assert {item["id"] for item in list_cases(kpi="active", page=1, page_size=50, db=db)["items"]} == {"active", "awaiting", "courier"}
    assert {item["id"] for item in list_cases(kpi="new_today", page=1, page_size=50, db=db)["items"]} == {"active", "awaiting", "resolved"}
    assert [item["id"] for item in list_cases(kpi="awaiting_customer", search="323501", page=1, page_size=50, db=db)["items"]] == ["awaiting"]
    assert [item["id"] for item in list_cases(kpi="courier_pending", page=1, page_size=50, db=db)["items"]] == ["courier"]
    assert [item["id"] for item in list_cases(kpi="resolved_today", page=1, page_size=50, db=db)["items"]] == ["resolved"]
    assert [item["id"] for item in list_cases(kpi="over_sla", page=1, page_size=50, db=db)["items"]] == ["courier"]


def test_confirmed_canonical_delivery_resolves_active_ndr_and_preserves_history(db):
    now = datetime.now(timezone.utc)
    case = NDRCase(id="delivered-ndr", source_identity="awb:DELIVERED1", awb="DELIVERED1", provider="delhivery", order_number="323027", source_lifecycle="active", current_status="courier_pending", priority="high", delivery_attempts=2, first_ndr_at=now, last_synced_at=now, products=[], cod_amount=0)
    db.add_all([
        case,
        NDREvent(id="historic-action", case_id=case.id, event_type="customer_contacted", description="Customer contacted", actor_name="Operator"),
        ShiprocketShipment(order_id="shopify-1", provider="delhivery", provider_order_id="323027", awb="DELIVERED1", normalized_status="delivered", terminal_status="delivered", latest_status="Delivered", shopify_fulfillment_status="success"),
    ])
    db.commit()

    active = list_cases(kpi="active", page=1, page_size=50, db=db)

    assert active["items"] == []
    db.refresh(case)
    assert (case.current_status, case.source_lifecycle) == ("resolved", "resolved")
    assert (case.resolution_outcome, case.resolution_source) == ("delivered", "provider")
    assert case.resolved_at is not None
    events = db.scalars(select(NDREvent).where(NDREvent.case_id == case.id)).all()
    assert {event.event_type for event in events} == {"customer_contacted", "delivered_resolution"}


def test_stale_import_cannot_reactivate_canonically_delivered_ndr(db):
    db.add(ShiprocketShipment(order_id="shopify-2", provider="delhivery", provider_order_id="323223", awb="SR123", normalized_status="delivered"))
    db.commit()

    import_ndr(db, payload("delivered-first"))
    case = db.scalar(select(NDRCase).where(NDRCase.source_identity == "awb:SR123"))
    assert case.current_status == "resolved"

    import_ndr(db, payload("delivered-stale"))
    db.refresh(case)
    assert (case.current_status, case.source_lifecycle) == ("resolved", "resolved")
    assert len(db.scalars(select(NDREvent).where(NDREvent.case_id == case.id, NDREvent.event_type == "delivered_resolution")).all()) == 1


def test_shopify_fulfilled_alone_does_not_resolve_ndr_and_unresolved_case_stays_active(db):
    db.add(ShiprocketShipment(order_id="shopify-3", provider="delhivery", provider_order_id="323500", awb="SR123", booking_status="booked", latest_status="Manifested", normalized_status="booked", shopify_fulfillment_status="success"))
    db.commit()

    import_ndr(db, payload("fulfilled-only"))
    case = db.scalar(select(NDRCase).where(NDRCase.source_identity == "awb:SR123"))
    assert (case.current_status, case.source_lifecycle) == ("new", "active")
    assert [item["id"] for item in list_cases(kpi="active", page=1, page_size=50, db=db)["items"]] == [case.id]


@pytest.mark.parametrize("status", ["RTO In Transit", "RTO Delivered", "RTO Initiated", "Cancelled"])
def test_confirmed_terminal_outcome_resolves_ndr_and_preserves_history(db, status):
    now = datetime.now(timezone.utc)
    case = NDRCase(id=f"terminal-{status}", source_identity=f"awb:{status}", awb=status, provider="delhivery", order_number="322264", source_lifecycle="active", current_status="new", priority="high", delivery_attempts=1, first_ndr_at=now, last_synced_at=now, products=[], cod_amount=0)
    db.add_all([case, NDREvent(id=f"history-{status}", case_id=case.id, event_type="operator_action", description="Preserved", actor_name="Operator"), ShiprocketShipment(order_id=f"shipment-{status}", provider="delhivery", provider_order_id="322264", awb=status, latest_status=status, terminal_status=status)])
    db.commit()
    assert list_cases(kpi="active", page=1, page_size=50, db=db)["items"] == []
    db.refresh(case); assert case.resolution_source == "provider"
    assert case.resolution_outcome == ("rto_confirmed" if status.startswith("RTO") else None)
    assert {event.event_type for event in db.scalars(select(NDREvent).where(NDREvent.case_id == case.id)).all()} == {"operator_action", "terminal_shipment_resolution"}

def test_stale_active_322264_resolves_from_canonical_rto_event_and_enriches_product(db):
    now=datetime.now(timezone.utc);case=NDRCase(id="322264",source_identity="awb:4829510010776",awb="4829510010776",provider="delhivery",order_number="322264",source_lifecycle="active",current_status="new",priority="high",delivery_attempts=1,first_ndr_at=now,last_synced_at=now,products=[],cod_amount=0)
    db.add_all([case,ShipmentEvent(id="rto",order_id="6819",order_number="322264",provider="delhivery",awb="4829510010776",normalized_status="rto_delivered",recorded_at=now,source="poll",deduplication_key="rto"),OrderReadModel(order_id="6819",order_number="322264",customer_name="Customer",payment_type="cod",order_value=999,products=[{"product_name":"Roasted Makhana","quantity":1,"price":999}],updated_at=now)]);db.commit()
    assert list_cases(kpi="active",page=1,page_size=50,db=db)["items"]==[]
    db.refresh(case);assert case.current_status=="resolved"

@pytest.mark.parametrize("status", ["Delivered", "RTO Initiated", "RTO In Transit", "RTO Delivered", "Returned to Seller", "Return Completed"])
def test_shadowfax_terminal_labels_resolve_exact_awb_at_active_read(status, db):
    now=datetime.now(timezone.utc); awb=f"SF-{status}"
    case=NDRCase(id=awb,source_identity=f"awb:{awb}",awb=awb,provider="shadowfax",order_number="323027",source_lifecycle="active",current_status="courier_pending",priority="medium",delivery_attempts=2,first_ndr_at=now,last_synced_at=now,products=[],cod_amount=0)
    db.add_all([case,ShipmentEvent(id=f"event-{status}",order_id="shopify-323027",order_number="323027",provider="shadowfax",awb=awb,provider_status_code="opaque-status-id",normalized_status=status,recorded_at=now,source="api_poll",deduplication_key=f"key-{status}")]);db.commit()
    assert list_cases(page=1,page_size=50,db=db)["items"]==[]
    db.refresh(case);assert case.current_status=="resolved"
