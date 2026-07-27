from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.ndr import NDRAction, case_action
from app.db.base import Base
from app.models.ndr import NDRCase, NDREvent, NDRSyncRun
from app.models.shiprocket import ShiprocketShipment
from app.models.user import User
from app.schemas.orders import OrderProduct, ShippingAddress, ShopifyOrder
from app.services.courier_platform.models import NormalizedShipmentStatus, TrackingResult
from app.services.ndr import sync_ndr
from app.services.shopify import ShopifyService


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ndr.db'}")
    Base.metadata.create_all(engine); session = sessionmaker(bind=engine)()
    try: yield session
    finally: session.close(); engine.dispose()


def order():
    return ShopifyOrder(order_id="1", order_number="323500", created_date="2026-07-27T00:00:00Z", customer_name="Customer", phone="9999999999", shipping_address=ShippingAddress(name="Customer", address="10 Main Road", city="Pune", state="MH", pincode="411001"), products=[OrderProduct(product_name="Snack Box", quantity=2, price=Decimal("500"))], total_amount=Decimal("2500"), cod_collectable_amount=Decimal("2500"), payment_type="cod", tags=[])


@pytest.mark.anyio
async def test_happy_path_sync_and_resolution_preserves_manual_state(db, monkeypatch):
    owner = User(username="owner", display_name="Ajit", password_hash="unused", role="owner", is_active=True)
    db.add_all([owner, ShiprocketShipment(order_id="1", provider="shadowfax", awb="SFX123", courier_name="Shadowfax", normalized_status="ndr")]); db.commit(); db.refresh(owner)
    async def latest(_self, force_refresh=False): return [order()]
    class Adapter:
        async def track_shipment(self, _shipment):
            return TrackingResult(provider="shadowfax", status=NormalizedShipmentStatus.NDR, provider_status="NDR", latest_tracking_at=datetime.now(timezone.utc), ndr_reason="Customer unavailable", ndr_attempt=2, tracking_url="https://track.example/SFX123")
    monkeypatch.setattr(ShopifyService, "get_latest_orders", latest)
    monkeypatch.setattr("app.services.ndr.courier_registry.get", lambda _provider: Adapter())
    run = await sync_ndr(db, trigger="manual", actor=owner)
    assert run.status == "completed" and run.cases_created == 1
    case = db.scalar(select(NDRCase).where(NDRCase.awb == "SFX123"))
    assert case.customer_name == "Customer" and case.priority == "high" and case.delivery_attempts == 2
    request = SimpleNamespace(state=SimpleNamespace(auth_user=owner))
    resolved = case_action(case.id, NDRAction(action="resolve", note="Customer requested closure"), request, db)
    assert resolved["current_status"] == "resolved"
    await sync_ndr(db, trigger="scheduler")
    db.refresh(case)
    assert case.current_status == "resolved" and case.resolution_note == "Customer requested closure"
    assert db.scalar(select(NDRSyncRun).where(NDRSyncRun.status == "running")) is None
    assert len(db.scalars(select(NDREvent).where(NDREvent.case_id == case.id)).all()) >= 2
