from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from app.api.routes import orders as routes
from app.api.routes.orders import _base_filtered_orders, _engage_category, _full_counts
from app.db.base import Base
from app.repositories.shiprocket import get_shipment, snapshot, sync_engage_orders
from app.services.shiprocket import ShiprocketService
from tests.test_orders_pagination import queue_order


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.mark.parametrize("pending,successful,disabled", [(0, 1, 6), ("0", "1", "6")])
def test_engage_response_preserves_numeric_and_string_values(pending, successful, disabled):
    db = session()
    now = datetime.now(timezone.utc)
    engage = {"engage_order_id": 99, "order_confirmation": successful, "order_confirmation_message": "sent", "address_confirmation": pending, "address_confirmation_message": "pending", "cod_to_prepaid": disabled, "cod_to_prepaid_message": "not sent", "future_field": {"kept": True}}
    sync_engage_orders(db, {" 323444 ": "shopify-1"}, [{"id": 77, "channel_order_id": 323444, "engage": engage}], now)
    stored = get_shipment(db, "shopify-1")
    saved = snapshot(stored)
    assert saved["engage_order_id"] == "99"
    assert saved["order_confirmation"] == successful
    assert saved["address_confirmation"] == pending
    assert saved["cod_to_prepaid"] == disabled
    assert stored.provider_order_id == "323444"
    assert stored.engage_raw_status == engage
    assert "engage_raw_status" not in saved


def test_absent_engage_clears_existing_fields_without_failure():
    db = session()
    now = datetime.now(timezone.utc)
    sync_engage_orders(db, {"1": "shopify-1"}, [{"id": 7, "channel_order_id": "1", "engage": {"order_confirmation": 1}}], now)
    sync_engage_orders(db, {"1": "shopify-1"}, [{"id": 7, "channel_order_id": "1", "engage": None}], now)
    saved = get_shipment(db, "shopify-1")
    assert saved.order_confirmation is None
    assert saved.engage_raw_status is None


def test_engage_filter_categories_and_summary_counts():
    assert [_engage_category(value) for value in (0, "0", 1, "1", 6, "6", "NA", 42, {"future": True}, None)] == ["pending", "pending", "successful", "successful", "disabled", "disabled", "disabled", "unknown", "unknown", "unknown"]
    db = session()
    orders = [queue_order("1", order_confirmation=0, address_confirmation=0, cod_to_prepaid=0), queue_order("2", order_confirmation=1, address_confirmation=6, cod_to_prepaid="NA")]
    counts = _full_counts(orders, datetime.now(timezone.utc), db)
    assert counts["awaiting_order_confirmation"] == 1
    assert counts["awaiting_address_verification"] == 1
    assert counts["cod_conversion_pending"] == 1


def test_engage_filters_use_the_same_category_mapping():
    orders = [
        queue_order("1", order_confirmation="0"),
        queue_order("2", order_confirmation=1),
        queue_order("3", order_confirmation="NA"),
        queue_order("4", order_confirmation={"future": True}),
    ]
    for category, expected in (("pending", "1"), ("successful", "2"), ("disabled", "3"), ("unknown", "4")):
        filtered = _base_filtered_orders(orders, "", "all", "all", order_confirmation=category)
        assert [order.order_number for order in filtered] == [expected]


@pytest.mark.anyio
async def test_orders_api_accepts_unknown_value_without_exposing_raw_json(monkeypatch):
    order = queue_order("5", order_confirmation={"future": True})

    async def load(_db):
        return [order]

    monkeypatch.setattr(routes, "_load_orders", load)
    page = await routes.list_orders(order_confirmation="unknown", db=None)
    payload = page.model_dump()
    assert payload["items"][0]["order_confirmation"] == {"future": True}
    assert "engage_raw_status" not in str(payload)


@pytest.mark.anyio
async def test_invalid_engage_filter_is_rejected(monkeypatch):
    async def load(_db):
        return []

    monkeypatch.setattr(routes, "_load_orders", load)
    with pytest.raises(Exception) as error:
        await routes.list_orders(order_confirmation="invented", db=None)
    assert getattr(error.value, "status_code", None) == 422


@pytest.mark.anyio
async def test_existing_orders_request_enables_web_response_fields(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": []}

    async def get(_url, *, params=None):
        calls.append(params)
        return Response()

    service = ShiprocketService()
    monkeypatch.setattr(service, "_get", get)
    await service.list_new_orders(force_refresh=True)
    assert len(calls) == 1
    assert calls[0]["is_web"] == 1
