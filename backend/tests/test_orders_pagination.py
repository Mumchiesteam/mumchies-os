from datetime import datetime, timedelta, timezone

import pytest

from app.api.routes import orders as routes
from app.services.shopify import ShopifyService
from tests.test_operations_upgrade import raw_order


def make_orders(count: int):
    result = []
    for index in range(count):
        raw = {**raw_order(), "id": index + 1, "name": f"#{index + 1}", "order_number": index + 1}
        result.append(ShopifyService._to_order(raw).model_copy(update={
            "order_id": str(index + 1),
            "order_number": str(index + 1),
            "created_date": (datetime.now(timezone.utc) - timedelta(minutes=index)).isoformat(),
        }))
    return result


def queue_order(number: str, **updates):
    raw = {**raw_order(), "id": int(number), "name": f"#{number}", "order_number": int(number)}
    return ShopifyService._to_order(raw).model_copy(update={"order_id": number, "order_number": number, **updates})


@pytest.mark.anyio
async def test_orders_default_page_is_20_with_totals(monkeypatch):
    monkeypatch.setattr(routes, "_load_orders", lambda _db: None)
    orders = make_orders(105)

    async def load(_db):
        return orders

    monkeypatch.setattr(routes, "_load_orders", load)
    page = await routes.list_orders(db=None)
    assert len(page.items) == 20
    assert (page.page, page.page_size, page.total, page.total_pages) == (1, 20, 105, 6)


@pytest.mark.anyio
@pytest.mark.parametrize("page_size", [50, 100])
async def test_orders_support_50_and_100_rows(monkeypatch, page_size):
    async def load(_db):
        return make_orders(105)

    monkeypatch.setattr(routes, "_load_orders", load)
    first = await routes.list_orders(page=1, page_size=page_size, db=None)
    second = await routes.list_orders(page=2, page_size=page_size, db=None)
    assert len(first.items) == page_size
    assert second.items[0].order_id == str(page_size + 1)
    assert second.total_pages == (3 if page_size == 50 else 2)


@pytest.mark.anyio
async def test_orders_empty_page_and_search(monkeypatch):
    async def load(_db):
        return make_orders(4)

    monkeypatch.setattr(routes, "_load_orders", load)
    page = await routes.list_orders(search="does-not-exist", db=None)
    assert page.items == []
    assert (page.total, page.total_pages, page.page) == (0, 1, 1)


@pytest.mark.anyio
async def test_full_counts_do_not_follow_page_size_or_page(monkeypatch):
    async def load(_db):
        return make_orders(64)

    monkeypatch.setattr(routes, "_load_orders", load)
    page_1_20 = await routes.list_orders(page=1, page_size=20, queue="fresh", db=None)
    page_2_20 = await routes.list_orders(page=2, page_size=20, queue="fresh", db=None)
    page_1_50 = await routes.list_orders(page=1, page_size=50, queue="fresh", db=None)
    page_1_100 = await routes.list_orders(page=1, page_size=100, queue="fresh", db=None)
    for result in (page_1_20, page_2_20, page_1_50, page_1_100):
        assert result.total == 64
        assert result.counts["fresh"] == 64
        assert result.counts["new_orders"] == 64
        assert result.counts["all"] == 64
    assert len(page_1_20.items) == len(page_2_20.items) == 20


def test_untouched_prepaid_is_fresh_regardless_of_age():
    order = queue_order("101", payment_type="prepaid", created_date="2025-01-01T00:00:00+00:00", human_action_count=0)
    assert routes._is_fresh_order(order) is True


def test_cod_no_call_and_attempt_one_unresolved_are_fresh():
    no_call = queue_order("102", payment_type="cod", call_attempt_count=0, latest_call_result=None)
    attempt_one = queue_order("103", payment_type="cod", call_attempt_count=1, latest_call_result="No Answer", human_action_count=1)
    assert routes._is_fresh_order(no_call) is True
    assert routes._is_fresh_order(attempt_one) is True


def test_cod_attempt_two_is_previous_pending():
    order = queue_order("104", payment_type="partial_cod", call_attempt_count=2, latest_call_result="No Answer", human_action_count=2)
    assert routes._is_fresh_order(order) is False
    assert routes._matches_queue(order, "previous", datetime.now(timezone.utc)) is True


@pytest.mark.parametrize("updates", [
    {"fulfillment_status": "fulfilled", "operational_status": "Shipped"},
    {"cancelled_at": "2026-07-25T00:00:00+00:00", "operational_status": "Cancelled"},
    {"operational_status": "Shipped"},
    {"latest_call_result": "Cancelled", "call_attempt_count": 1},
    {"shipment": {"booking_status": "booked", "awb": "AWB1"}, "operational_status": "Booked"},
])
def test_completed_orders_are_excluded_from_operations(updates):
    order = queue_order("105", **updates)
    assert routes._requires_operational_action(order) is False


@pytest.mark.anyio
async def test_operations_always_equals_fresh_plus_previous(monkeypatch):
    values = [
        queue_order("106", payment_type="prepaid", human_action_count=0),
        queue_order("107", payment_type="cod", call_attempt_count=2, latest_call_result="Busy", human_action_count=2),
        queue_order("108", fulfillment_status="fulfilled", operational_status="Shipped"),
    ]
    async def load(_db): return values
    monkeypatch.setattr(routes, "_load_orders", load)
    result = await routes.list_orders(db=None)
    assert result.counts["operations"] == result.counts["fresh"] + result.counts["previous"] == 2


@pytest.mark.anyio
async def test_reconciliation_sets_and_mismatch_classification(monkeypatch):
    os_only = queue_order("201", payment_type="cod", call_attempt_count=0)
    both = queue_order("202", payment_type="prepaid", human_action_count=0)
    stale = queue_order("203", fulfillment_status="fulfilled", operational_status="Shipped")
    async def load(_db, force_refresh=False): return [os_only, both, stale]
    async def new(_self, force_refresh=False):
        return [
            {"id": 2, "channel_order_id": "202", "status": "NEW"},
            {"id": 3, "channel_order_id": "203", "status": "NEW", "products": [{"status": "CANCELED"}]},
        ]
    async def find(_self, number): return None if number == "201" else {"channel_order_id": number, "status": "NEW"}
    monkeypatch.setattr(routes, "_load_orders", load)
    monkeypatch.setattr(routes.ShiprocketService, "list_new_orders", new)
    monkeypatch.setattr(routes.ShiprocketService, "find_existing_order", find)
    result = await routes.reconciliation_summary(db=None)
    assert result["operations_queue"] == 2
    assert result["present_in_both"] == 1
    assert result["missing_in_shiprocket"] == 1
    assert result["only_in_os"] == [{"order_number": "201", "reason": "not yet synced to Shiprocket", "shiprocket_status": None}]
    assert result["only_in_shiprocket"][0]["reason"] == "stale Shiprocket state"
    assert result["duplicate_mapping_anomalies"] == []
    assert [item["order_number"] for item in result["datasets"]["operations"]] == ["201", "202"]
    assert result["datasets"]["cleanup_pending"][0]["reason"] == "stale Shiprocket state"
    assert result["datasets"]["missing_in_shiprocket"][0]["reason"] == "not yet synced to Shiprocket"
