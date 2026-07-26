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
