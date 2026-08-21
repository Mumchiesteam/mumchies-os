from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

import pytest

from app.api.routes import couriers
from app.api.routes.couriers import BookingPayload, _booking_selection_matches
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


def test_booking_requires_the_same_persisted_canonical_courier() -> None:
    selected = {"provider": "shiprocket", "courier_id": "43", "courier_name": "Delhivery Surface", "mode": "surface"}
    payload = BookingPayload(weight_kg=0.5, courier_id="43", provider="shiprocket", courier_name="Delhivery Surface", draft_order_id="1", address_revision=0, booking_context_hash="test")
    assert _booking_selection_matches(selected, payload)
    assert not _booking_selection_matches(None, payload)
    assert not _booking_selection_matches({**selected, "provider": "delhivery"}, payload)
    assert not _booking_selection_matches({**selected, "courier_id": "44"}, payload)
    assert not _booking_selection_matches({**selected, "courier_name": "Different Service"}, payload)


def test_courier_lookup_clears_stored_selection_before_returning_quotes() -> None:
    source = inspect.getsource(couriers.shiprocket_serviceability)
    assert "save_selected_courier(order_id, None)" in source
    assert '"booking_readiness"' in source
    assert '"eligible": eligibility.eligible' in source


def test_booking_returns_before_noncritical_post_booking_work() -> None:
    source = inspect.getsource(couriers.shiprocket_book_shipment)
    assert "background_tasks.add_task(_run_post_booking_work" in source
    assert "await _sync_shopify_after_booking" not in source
    assert "await _cleanup_unused_shiprocket_order" not in source
    assert "OrderOperationsStore.save_selected_courier(order_id, selected)" not in source


def test_post_booking_failures_remain_persisted_and_actionable() -> None:
    source = inspect.getsource(couriers._run_post_booking_work)
    assert "ShopifyFulfillmentSynchronizer().sync" in source
    assert "_cleanup_unused_shiprocket_order" in source
    assert "OrderOperationsStore.record_timeline_event" in source
    assert 'provider in {"delhivery", "shadowfax"}' in source


def test_direct_cleanup_is_pending_before_background_work_and_retry_uses_shopify_number() -> None:
    booking = inspect.getsource(couriers.shiprocket_book_shipment)
    retry = inspect.getsource(couriers.retry_unused_shiprocket_cleanup)
    assert 'details={"status": "pending", "reason": "confirmed_delhivery_booking"}' in booking
    assert 'shipment.provider not in {"delhivery", "shadowfax"}' in retry
    assert "order = await _load_order(order_id)" in retry
    assert "order.order_number" in retry
    assert "shipment.provider_order_id or order_id" not in retry


def test_confirmation_can_reuse_display_cache_but_booking_keeps_fresh_shopify_guard() -> None:
    preview = inspect.getsource(couriers.preview_booking_context)
    booking = inspect.getsource(couriers.shiprocket_book_shipment)
    assert "get_cached_order(order_id) or await _load_order(order_id)" in preview
    assert "order = await _load_order(order_id)" in booking
    assert "get_cached_order" not in booking
