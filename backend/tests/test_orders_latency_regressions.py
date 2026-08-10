from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.api.routes import couriers
from app.schemas.orders import ShopifyOrder
from app.services.shopify import ShopifyService


def _order() -> ShopifyOrder:
    return ShopifyOrder(
        order_id="123", order_number="324999", created_date=datetime.now(timezone.utc).isoformat(),
        customer_name="Test", total_amount=508, order_total=508, payment_type="cod",
        products=[], tags=[],
    )


@pytest.mark.anyio
async def test_single_order_context_does_not_load_operational_population(monkeypatch: pytest.MonkeyPatch) -> None:
    async def one(self, order_id: str):  # noqa: ANN001
        assert order_id == "123"
        return _order()

    async def population(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("15-day population must not be loaded")

    monkeypatch.setattr(ShopifyService, "get_order", one)
    monkeypatch.setattr(ShopifyService, "get_latest_orders", population)
    assert (await couriers._load_order("123")).order_number == "324999"


@pytest.mark.anyio
async def test_reporting_lock_cannot_block_operational_lock() -> None:
    assert ShopifyService._orders_lock is not ShopifyService._reporting_orders_lock
    entered = asyncio.Event()
    release = asyncio.Event()

    async def reporting_holder() -> None:
        async with ShopifyService._reporting_orders_lock:
            entered.set()
            await release.wait()

    task = asyncio.create_task(reporting_holder())
    await entered.wait()
    acquired = False
    async with asyncio.timeout(0.1):
        async with ShopifyService._orders_lock:
            acquired = True
    release.set()
    await task
    assert acquired is True


@pytest.mark.anyio
async def test_operational_fetch_returns_before_repeat_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ShopifyService()
    orders = [_order()]
    repeat_started = asyncio.Event()
    repeat_release = asyncio.Event()

    async def fetch(_limit=None):  # noqa: ANN001
        return orders

    async def repeat(_orders):  # noqa: ANN001
        repeat_started.set()
        await repeat_release.wait()

    monkeypatch.setattr(service, "_fetch_orders", fetch)
    monkeypatch.setattr(service, "_enrich_repeat_customer_history", repeat)
    ShopifyService._orders_cache.clear()
    ShopifyService._repeat_refresh_tasks.clear()
    result = await service.get_latest_orders()
    assert result == orders
    await repeat_started.wait()
    assert orders[0].customer_orders_count is None
    repeat_release.set()
    await next(iter(ShopifyService._repeat_refresh_tasks.values()))
