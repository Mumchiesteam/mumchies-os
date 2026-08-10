from datetime import date, datetime, timezone
import inspect
from decimal import Decimal

from app.api.routes import analytics as analytics_route
from app.api.routes.analytics import _change, _filter, _geography, _payment, _previous_period, _products, _state, _summary, _trend
from app.api.routes.dashboard import _period
from app.schemas.orders import OrderProduct, ShippingAddress, ShopifyOrder


def order(identity: str, *, payment="cod", repeat=1, cancelled=False, fulfilled=False, created="2026-08-08T05:00:00Z", quantity=2, price=40, state=None, city=None, pincode=None) -> ShopifyOrder:
    return ShopifyOrder(order_id=identity, order_number=identity, created_date=created, cancelled_at=created if cancelled else None, customer_id=identity, customer_orders_count=repeat, fulfillment_status="fulfilled" if fulfilled else "unfulfilled", products=[OrderProduct(product_name="Makhana", sku="M1", quantity=quantity, price=Decimal(price))], total_amount=Decimal("100"), order_total=Decimal("100"), payment_type=payment, shipping_address=ShippingAddress(state=state, city=city, pincode=pincode) if any((state, city, pincode)) else None, tags=[])


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


def test_geography_aggregation_normalization_drilldown_and_deltas() -> None:
    current = [order("1", state="KA", city=" bengaluru ", pincode="560076", repeat=2), order("2", payment="prepaid", state="karnataka", city="BENGALURU", pincode="560077"), order("3")]
    previous = [order("old", state="Karnataka", city="Bengaluru", pincode="560076")]
    geo = _geography(current, previous)
    assert _state(" MH ") == "Maharashtra"
    assert geo["states"][0]["state"] == "Karnataka" and geo["states"][0]["orders"] == 2
    assert geo["states"][0]["orders_change"] == 1 and geo["states"][0]["value_change"] == 100
    assert geo["cities"]["Karnataka"][0]["city"] == "Bengaluru"
    assert {row["pincode"] for row in geo["pincodes"]["Karnataka|Bengaluru"]} == {"560076", "560077"}
    assert geo["states"][1]["state"] == "Unknown"
    assert geo["data_quality"] == {"missing_state": 1, "missing_city": 1, "missing_pincode": 1}


def test_geography_filters_and_products_use_canonical_classification() -> None:
    rows = [order("cod-repeat", repeat=2, state="KA", city="Bengaluru", pincode="1"), order("prepaid-new", payment="prepaid", state="MH", city="Mumbai", pincode="2")]
    assert [row.order_id for row in _filter(rows, "cod", "repeat")] == ["cod-repeat"]
    geo = _geography(_filter(rows, "prepaid", "new"), [])
    assert geo["states"][0]["state"] == "Maharashtra"
    assert geo["products"]["state:Maharashtra"][0]["product"] == "Makhana"
    assert geo["products"]["state:Maharashtra"][0]["orders"] == 1


def test_analytics_geography_stays_on_reporting_shopify_path() -> None:
    source = inspect.getsource(analytics_route._build)
    assert "get_orders_created_between" in source
    assert "get_latest_orders" not in source
