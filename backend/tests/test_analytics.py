from datetime import date, datetime, timezone
import inspect
from decimal import Decimal

from app.api.routes import analytics as analytics_route
from app.api.routes.analytics import _change, _payment, _previous_period, _products, _summary, _trend
from app.api.routes.dashboard import _period
from app.schemas.orders import OrderProduct, ShopifyOrder


def order(identity: str, *, payment="cod", repeat=1, cancelled=False, fulfilled=False, created="2026-08-08T05:00:00Z", quantity=2, price=40) -> ShopifyOrder:
    return ShopifyOrder(order_id=identity, order_number=identity, created_date=created, cancelled_at=created if cancelled else None, customer_orders_count=repeat, fulfillment_status="fulfilled" if fulfilled else "unfulfilled", products=[OrderProduct(product_name="Makhana", sku="M1", quantity=quantity, price=Decimal(price))], total_amount=Decimal("100"), order_total=Decimal("100"), payment_type=payment, tags=[])


def test_all_periods_and_previous_equivalent() -> None:
    now = datetime(2026, 8, 9, 10, tzinfo=timezone.utc)
    for preset in ("today", "yesterday", "last_7_days", "month_to_date", "last_30_days"):
        start, end, _ = _period(preset, None, None, now); previous_start, previous_end = _previous_period(start, end)
        assert previous_end == start and previous_end - previous_start == end - start
    start, end, _ = _period("custom", date(2026, 6, 1), date(2026, 6, 20), now); assert (end - start).days == 20


def test_business_customer_payment_product_and_trend_metrics() -> None:
    rows = [order("repeat", repeat=2, fulfilled=True), order("prepaid", payment="prepaid", quantity=1), order("partial", payment="partial_cod", quantity=1), order("cancelled", cancelled=True, fulfilled=True)]
    summary = _summary(rows)
    assert summary["total_orders"] == 4 and summary["active_orders"] == 3
    assert summary["order_value"] == 300 and summary["aov"] == 100
    assert summary["items_per_order"] == 1.5 and summary["cancellation_percent"] == 25
    assert summary["fulfilled_orders"] == 1 and summary["fulfillment_percent"] == 33.3
    assert summary["repeat_percent"] == 33.3
    payment = {row["key"]: row for row in _payment(rows)}
    assert payment["partial_cod"]["orders"] == 1 and payment["cod"]["cancellation_percent"] == 50
    products = _products(rows, [order("old", quantity=1)])
    assert products[0]["quantity"] == 4 and products[0]["orders"] == 3 and products[0]["quantity_change"] == 3
    trend = _trend(rows, datetime(2026, 8, 8, tzinfo=timezone.utc), datetime(2026, 8, 10, tzinfo=timezone.utc))
    assert trend["granularity"] == "hour" and sum(point["orders"] for point in trend["points"]) == 3
    assert _change(120, 100)["percent"] == 20 and _change(30, 25, points=True)["points"] == 5


def test_analytics_has_no_reconciliation_dependency() -> None:
    assert "reconciliation" not in inspect.getsource(analytics_route).casefold()
