from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.labels import DispatchPayload, label_queue, manifest_dispatch, return_dispatch_to_ready
from app.db.base import Base
from app.models.user import User
from app.repositories.shiprocket import upsert_shipment


@pytest.fixture
def db():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def request(role="operator"):
    return SimpleNamespace(state=SimpleNamespace(auth_user=User(username=role,display_name=role.title(),password_hash="x",role=role,is_active=True)))


@pytest.mark.anyio
async def test_confirmed_booking_derives_ready_and_failed_booking_does_not(db):
    upsert_shipment(db,"booked",provider="delhivery",booking_status="booked",awb="AWB1",booked_at=datetime.now(timezone.utc))
    upsert_shipment(db,"failed",provider="delhivery",booking_status="booking_failed",awb=None)
    result=await label_queue(db)
    assert [row["order_id"] for row in result["ready_to_ship"]]==["booked"]
    assert result["manifested"]==[]


@pytest.mark.anyio
async def test_internal_manifest_and_admin_correction_do_not_change_provider_state(db):
    shipment=upsert_shipment(db,"booked",provider="delhivery",booking_status="booked",awb="AWB1",latest_status="In Transit",normalized_status="in_transit")
    result=manifest_dispatch(DispatchPayload(order_ids=["booked"],confirmed=True),request(),db)
    db.refresh(shipment)
    assert (shipment.dispatch_status,shipment.manifested_by)==("manifested","Operator")
    assert shipment.latest_status=="In Transit" and result["manifested_delta"]==1
    return_dispatch_to_ready(DispatchPayload(order_ids=["booked"],confirmed=True),request("admin"),db)
    db.refresh(shipment)
    assert shipment.dispatch_status=="ready_to_ship" and shipment.manifested_at is None and shipment.awb=="AWB1"
