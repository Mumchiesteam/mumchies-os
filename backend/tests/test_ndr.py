from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.ndr import NDRAction, NDRImportPayload, case_action, import_cases
from app.core.config import settings
from app.db.base import Base
from app.models.ndr import NDRCase, NDREvent, NDRImportRun
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
    case_action(case.id, NDRAction(action="resolve", note="Keep closed"), request, db)
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
