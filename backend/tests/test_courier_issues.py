from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import courier_issues
from app.api.routes.courier_issues import CourierIssuePayload
from app.db.base import Base
from app.models.courier_issue import CourierIssue
from app.models.shipment_event import ShipmentEvent
from app.models.shiprocket import ShiprocketShipment
from app.models.user import User


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def request():
    return SimpleNamespace(state=SimpleNamespace(auth_user=User(username="ajit", display_name="Ajit", password_hash="x", role="admin", is_active=True)))


def payload(**updates):
    values = dict(awb=" AWB-1 ", date_raised=date(2026, 8, 1), raised_by="Ajit", courier="Delhivery", issue_type="Delivery Issue", notes=" Check scan ", status="open", closure_date=None)
    values.update(updates)
    return CourierIssuePayload(**values)


def test_create_open_issue_trims_fields_and_calculates_age(db, monkeypatch):
    monkeypatch.setattr(courier_issues, "_today", lambda: date(2026, 8, 11))
    result = courier_issues.create_issue(payload(), request(), db)
    assert result | {"ignored": True}
    assert result["awb"] == "AWB-1"
    assert result["notes"] == "Check scan"
    assert result["status"] == "open" and result["closure_date"] is None and result["age"] == 10


@pytest.mark.parametrize("field", ["awb", "raised_by", "courier", "issue_type"])
def test_required_fields(field):
    with pytest.raises(Exception):
        payload(**{field: " "})


def test_close_defaults_date_and_reopen_clears_it(db, monkeypatch):
    monkeypatch.setattr(courier_issues, "_today", lambda: date(2026, 8, 11))
    created = courier_issues.create_issue(payload(), request(), db)
    closed = courier_issues.update_issue(created["id"], payload(status="closed"), request(), db)
    assert closed["closure_date"] == "2026-08-11" and closed["age"] == 10
    reopened = courier_issues.update_issue(created["id"], payload(status="open", closure_date=date(2026, 8, 11), notes="Edited"), request(), db)
    assert reopened["closure_date"] is None and reopened["notes"] == "Edited" and reopened["created_at"] == created["created_at"]


def test_filters_sort_and_age_kpis(db, monkeypatch):
    monkeypatch.setattr(courier_issues, "_today", lambda: date(2026, 8, 20))
    courier_issues.create_issue(payload(awb="OLD", date_raised=date(2026, 8, 1)), request(), db)
    courier_issues.create_issue(payload(awb="MID", date_raised=date(2026, 8, 10), courier="Shiprocket", raised_by="Rupesh", issue_type="RTO Issue"), request(), db)
    courier_issues.create_issue(payload(awb="NEW", date_raised=date(2026, 8, 19)), request(), db)
    result = courier_issues.list_issues("open", "M", "Shiprocket", "RTO Issue", "Rupesh", db)
    assert [item["awb"] for item in result["items"]] == ["MID"]
    assert result["kpis"] == {"open": 3, "open_over_7": 2, "open_over_15": 1, "closed_this_month": 0}


def test_awb_mapping_requires_one_canonical_shipment_and_consistent_order_number(db):
    shipment = ShiprocketShipment(order_id="gid-1", awb="TRACK-1", provider="delhivery")
    event = ShipmentEvent(id="e1", order_id="gid-1", order_number="324700", provider="delhivery", awb="TRACK-1", normalized_status="picked_up", recorded_at=datetime.now(timezone.utc), source="api_poll", deduplication_key="d1")
    db.add_all([shipment, event, CourierIssue(awb="TRACK-1", date_raised=date(2026, 8, 1), raised_by="Ajit", courier="Delhivery", issue_type="Delivery Issue", status="open")]); db.commit()
    mapped = courier_issues.list_issues("open", db=db)["items"][0]
    assert mapped["order_id"] == "gid-1" and mapped["order_number"] == "324700"
    db.add(ShiprocketShipment(order_id="gid-2", awb="TRACK-1", provider="shiprocket")); db.commit()
    ambiguous = courier_issues.list_issues("open", db=db)["items"][0]
    assert ambiguous["order_id"] is None and ambiguous["order_number"] is None


def test_export_respects_filters(db, monkeypatch):
    monkeypatch.setattr(courier_issues, "_today", lambda: date(2026, 8, 11))
    courier_issues.create_issue(payload(awb="KEEP", courier="Delhivery"), request(), db)
    courier_issues.create_issue(payload(awb="DROP", courier="Shiprocket"), request(), db)
    response = courier_issues.export_issues("open", "", "Delhivery", "", "", db)
    rows = list(load_workbook(BytesIO(response.body)).active.values)
    assert rows[1][0] == "KEEP" and len(rows) == 2
    assert "courier-issues-2026-08-11.xlsx" in response.headers["content-disposition"]


def test_register_has_no_provider_or_shopify_calls():
    import inspect
    source = inspect.getsource(courier_issues)
    assert "ShiprocketService" not in source
    assert "ShopifyService" not in source
    assert "httpx" not in source
