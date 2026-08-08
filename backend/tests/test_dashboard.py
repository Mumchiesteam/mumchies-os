from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.routes import dashboard as dashboard_route
from app.api.routes.dashboard import _business_metrics, _ndr_activity, _order_activity, _period
from app.schemas.orders import OrderProduct, ShopifyOrder


def order(order_id: str, *, payment: str = "cod", repeat: int = 1, cancelled: bool = False, products: list[OrderProduct] | None = None) -> ShopifyOrder:
    return ShopifyOrder(
        order_id=order_id, order_number=order_id, created_date="2026-08-09T05:00:00Z",
        cancelled_at="2026-08-09T06:00:00Z" if cancelled else None, customer_orders_count=repeat,
        products=products or [], total_amount=Decimal("100"), order_total=Decimal("100"), payment_type=payment, tags=[],
    )


def test_dashboard_date_periods_use_ist_business_days() -> None:
    now = datetime(2026, 8, 9, 10, tzinfo=timezone.utc)
    start, end, _ = _period("today", None, None, now)
    assert start.isoformat() == "2026-08-08T18:30:00+00:00"
    assert end.isoformat() == "2026-08-09T18:30:00+00:00"
    custom_start, custom_end, _ = _period("custom", date(2026, 6, 1), date(2026, 6, 30), now)
    assert (custom_end - custom_start).days == 30


def test_order_activity_uses_action_timestamp_and_unique_orders() -> None:
    operations = {
        "old-order": {"human_actions": [
            {"action": "call_logged", "timestamp": "2026-08-09T03:00:00", "operator": "Ajit"},
            {"action": "address_verified", "timestamp": "2026-08-09T04:00:00+00:00", "operator": "Ajit"},
        ]},
        "outside": {"human_actions": [{"action": "call_logged", "timestamp": "2026-08-08T03:00:00+00:00", "operator": "Ajit"}]},
        "rupesh": {"timeline_events": [{"action": "shipment_booked", "timestamp": "2026-08-09T05:00:00+00:00", "operator": "Rupesh"}]},
    }
    result = _order_activity(operations, datetime(2026, 8, 9, tzinfo=timezone.utc), datetime(2026, 8, 10, tzinfo=timezone.utc))
    assert result == {"Ajit": {"old-order"}, "Rupesh": {"rupesh"}}


def test_ndr_activity_is_unique_and_attributed() -> None:
    events = [
        SimpleNamespace(case_id="case-1", event_type="add_note", actor_name="Ajit", created_at=datetime(2026, 8, 9, 2, tzinfo=timezone.utc)),
        SimpleNamespace(case_id="case-1", event_type="resolve", actor_name="Ajit", created_at=datetime(2026, 8, 9, 3, tzinfo=timezone.utc)),
        SimpleNamespace(case_id="case-2", event_type="import_update", actor_name="Rupesh", created_at=datetime(2026, 8, 9, 3, tzinfo=timezone.utc)),
        SimpleNamespace(case_id="case-3", event_type="customer_contacted", actor_name="Rupesh", created_at=datetime(2026, 8, 9, 4, tzinfo=timezone.utc)),
    ]
    result = _ndr_activity(events, datetime(2026, 8, 9, tzinfo=timezone.utc), datetime(2026, 8, 10, tzinfo=timezone.utc))
    assert result == {"Ajit": {"case-1"}, "Rupesh": {"case-3"}}


def test_business_metrics_payment_repeat_cancelled_and_products() -> None:
    products = [OrderProduct(product_name="Makhana", sku="M1", quantity=2, price=Decimal("40"))]
    metrics = _business_metrics([
        order("cod", payment="cod", repeat=2, products=products),
        order("prepaid", payment="prepaid", products=products),
        order("partial", payment="partial_cod"),
        order("cancelled", cancelled=True, products=products),
    ], {"cod"})
    assert metrics["orders"] == {"total": 3, "value": 300.0, "repeat_percent": 33.3, "actioned": 1, "pending": 2, "cancelled_excluded": 1}
    assert metrics["payment_mix"] == {
        "cod": {"count": 1, "percent": 33.3}, "prepaid": {"count": 1, "percent": 33.3}, "partial_cod": {"count": 1, "percent": 33.3},
    }
    assert metrics["top_products"] == [{"product": "Makhana", "quantity": 4, "orders": 2, "order_value": 160.0}]


@pytest.mark.anyio
async def test_today_dashboard_reuses_operational_read_without_reconciliation_or_second_shopify_load(monkeypatch: pytest.MonkeyPatch) -> None:
    class Results:
        def all(self) -> list[object]: return []

    class Database:
        def scalars(self, statement: object) -> Results: return Results()

    async def operational(db: object) -> list[ShopifyOrder]: return []
    async def unexpected_reporting(self: object, start: datetime, end: datetime) -> list[ShopifyOrder]:
        raise AssertionError("Today must reuse the operational Shopify read")

    monkeypatch.setattr(dashboard_route.OrderOperationsStore, "all", lambda: {})
    monkeypatch.setattr(dashboard_route, "_load_orders", operational)
    monkeypatch.setattr(dashboard_route.ShopifyService, "get_orders_created_between", unexpected_reporting)

    start_at, end_at, label = dashboard_route._period("today", None, None)
    result = await dashboard_route._build_dashboard("today", start_at, end_at, label, Database())

    assert result["needs_attention"]["reconciliation_exceptions"] is None
    assert result["orders"]["total"] == 0


@pytest.mark.anyio
async def test_dashboard_returns_stale_snapshot_while_refresh_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = {"data": {"period": {"label": "Today"}, "orders": {"total": 9}}, "last_refreshed_at": "2026-08-09T00:00:00Z", "refresh_error": None}
    started: list[str] = []
    monkeypatch.setattr(dashboard_route.ReportSnapshotStore, "get", lambda key: snapshot)
    monkeypatch.setattr(dashboard_route, "_start_dashboard_refresh", lambda key, preset, start, end, label: started.append(key) or True)

    result = await dashboard_route.dashboard(preset="today", start=None, end=None, refresh=True)

    assert result["orders"]["total"] == 9
    assert result["last_refreshed_at"] == "2026-08-09T00:00:00Z"
    assert started
