from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.ndr import NDRImportPayload, list_cases, resolution_analytics, summary
from app.db.base import Base
from app.models.ndr import NDRCase, NDREvent
from app.services.ndr import serialize_case
from app.services.ndr_eligibility import is_ndr_eligible
from app.services.ndr_import import import_ndr


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'eligibility.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close(); engine.dispose()


def payload(run_id: str, status: str, reason: str = "") -> NDRImportPayload:
    return NDRImportPayload.model_validate({
        "schema_version": 1, "run_id": run_id, "generated_at": "2026-08-17T10:00:00Z",
        "source_health": {"shadowfax": {"status": "success"}}, "source_counts": {"shadowfax": 1},
        "rows": [{"source": "shadowfax", "order_id": "324921", "awb": "SF324921", "status": status, "failure_reason": reason, "attempts": 1}],
    })


@pytest.mark.parametrize("status", ["pickup not attempted", "pickup pending", "ready for pickup"])
def test_pre_pickup_status_is_not_ndr(status):
    assert not is_ndr_eligible(status)


def test_picked_up_with_genuine_delivery_failure_is_ndr():
    assert is_ndr_eligible("picked up", "delivery attempt failed - customer unavailable")


def test_generic_pending_or_attempted_is_not_ndr():
    assert not is_ndr_eligible("pending")
    assert not is_ndr_eligible("attempted")


def test_invalid_import_preserves_history_and_leaves_active_queue(db):
    import_ndr(db, payload("valid", "UNDELIVERED", "Customer unavailable"))
    case = db.scalar(select(NDRCase).where(NDRCase.order_number == "324921"))
    db.add(NDREvent(id="history", case_id=case.id, event_type="operator_action", description="Preserved", actor_name="Operator")); db.commit()

    import_ndr(db, payload("stale-invalid", "pickup_not_attempted"))
    db.refresh(case)
    assert case.source_lifecycle == "no_longer_reported"
    assert db.get(NDREvent, "history") is not None
    assert list_cases(kpi="active", page=1, page_size=50, db=db)["items"] == []


def test_active_read_and_serialization_hide_historical_pre_pickup_case(db):
    now = datetime.now(timezone.utc)
    case = NDRCase(id="legacy", source_identity="awb:LEGACY", awb="LEGACY", provider="shadowfax", order_number="324963", source_lifecycle="active", current_status="new", provider_status="Pickup not attempted", priority="low", delivery_attempts=0, first_ndr_at=now, last_synced_at=now, products=[], cod_amount=0)
    db.add(case); db.commit()
    assert list_cases(kpi="active", page=1, page_size=50, db=db)["items"] == []
    assert serialize_case(case)["source_lifecycle"] == "no_longer_reported"


def test_summary_and_analytics_do_not_repeat_terminal_reconciliation(db, monkeypatch):
    def unexpected(_db):
        raise AssertionError("read-only companion requests must not repeat terminal reconciliation")

    monkeypatch.setattr("app.api.routes.ndr.resolve_active_terminal_cases", unexpected)
    assert summary(db)["active_ndr"] == 0
    assert resolution_analytics(db=db)["open_cases"] == 0
