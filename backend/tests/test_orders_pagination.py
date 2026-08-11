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


def test_untouched_prepaid_remains_fresh_regardless_of_age():
    order = queue_order("101", payment_type="prepaid", created_date="2025-01-01T00:00:00+00:00", human_action_count=0)
    now = datetime(2026, 8, 11, 6, tzinfo=timezone.utc)
    assert routes._is_fresh_order(order, now) is True
    assert routes._matches_queue(order, "previous", now) is False


def test_failed_contact_is_previous_pending_even_when_created_today():
    no_call = queue_order("102", created_date="2026-08-11T04:30:00Z", payment_type="cod", call_attempt_count=0, latest_call_result=None)
    attempt_one = queue_order("103", created_date="2026-08-11T04:30:00Z", payment_type="cod", call_attempt_count=1, latest_call_result="No Answer", human_action_count=1)
    assert routes._is_fresh_order(no_call, QUEUE_NOW) is True
    assert routes._is_fresh_order(attempt_one, QUEUE_NOW) is False
    assert routes._matches_queue(attempt_one, "previous", QUEUE_NOW, "follow_up") is True


def test_cod_attempt_one_is_previous_pending():
    order = queue_order("104", payment_type="partial_cod", call_attempt_count=1, latest_call_result="No Answer", human_action_count=1)
    assert routes._is_fresh_order(order) is False
    assert routes._matches_queue(order, "previous", datetime.now(timezone.utc)) is True


@pytest.mark.parametrize("outcome", ["No Answer", "Busy", "Switched Off", "Callback Requested"])
def test_attempt_one_follow_up_outcomes_are_previous_pending(outcome):
    order = queue_order("109", payment_type="cod", call_attempt_count=1, latest_call_result=outcome, human_action_count=1)
    assert routes._matches_queue(order, "previous", datetime.now(timezone.utc)) is True


@pytest.mark.parametrize("outcome", ["Confirmed", "Wrong Number"])
def test_unresolved_non_follow_up_outcomes_use_fresh_fallback(outcome):
    order = queue_order("110", payment_type="cod", call_attempt_count=1, latest_call_result=outcome, human_action_count=1, operational_status="Ready for Booking" if outcome == "Confirmed" else "Needs Review")
    assert routes._matches_queue(order, "fresh", datetime.now(timezone.utc)) is True
    assert routes._matches_queue(order, "previous", datetime.now(timezone.utc)) is False
    assert order.call_attempt_count == 1


@pytest.mark.anyio
async def test_confirmed_unbooked_order_uses_fresh_fallback_and_retains_history(monkeypatch):
    confirmed = queue_order("111", payment_type="cod", call_attempt_count=1, latest_call_result="Confirmed", human_action_count=1, operational_status="Ready for Booking")
    async def load(_db): return [confirmed]
    monkeypatch.setattr(routes, "_load_orders", load)
    result = await routes.list_orders(queue="fresh", db=None)
    assert [item.order_number for item in result.items] == ["111"]
    assert result.counts["fresh"] == 1
    assert result.counts["previous"] == 0
    assert confirmed.call_attempt_count == 1


@pytest.mark.anyio
async def test_search_is_global_and_null_safe_across_queues(monkeypatch):
    values = [
        queue_order("301", payment_type="cod", call_attempt_count=0, customer_name="Fresh Person", phone=None),
        queue_order("302", payment_type="cod", call_attempt_count=1, latest_call_result="Busy", customer_name="Pending Person", phone="9990001111"),
        queue_order("303", payment_type="prepaid", human_action_count=1, customer_name="Printed Person", shipment={"booking_status": "booked", "awb": "A3", "label_last_printed_at": datetime.now(timezone.utc).isoformat()}),
    ]
    async def load(_db): return values
    monkeypatch.setattr(routes, "_load_orders", load)
    by_number = await routes.list_orders(queue="fresh", search="302", db=None)
    by_name = await routes.list_orders(queue="fresh", search="Pending Person", db=None)
    by_phone = await routes.list_orders(queue="fresh", search="9990001111", db=None)
    printed = await routes.list_orders(queue="fresh", search="Printed Person", db=None)
    assert [value.order_number for value in by_number.items] == ["302"]
    assert [value.order_number for value in by_name.items] == ["302"]
    assert [value.order_number for value in by_phone.items] == ["302"]
    assert [value.order_number for value in printed.items] == ["303"]


@pytest.mark.anyio
@pytest.mark.parametrize(("attempt", "expected"), [("1", "311"), ("2", "312"), ("3", "313"), ("4_plus", "314")])
async def test_previous_pending_attempt_filters_use_completed_attempt_count(monkeypatch, attempt, expected):
    values = [queue_order(str(310 + count), payment_type="cod", call_attempt_count=count, latest_call_result="Busy", human_action_count=count) for count in range(1, 6)]
    async def load(_db): return values
    monkeypatch.setattr(routes, "_load_orders", load)
    result = await routes.list_orders(queue="previous", attempt=attempt, db=None)
    if attempt == "4_plus":
        assert {value.order_number for value in result.items} == {"314", "315"}
    else:
        assert [value.order_number for value in result.items] == [expected]


@pytest.mark.anyio
async def test_attempt_filter_excludes_confirmed_orders(monkeypatch):
    values = [
        queue_order("316", payment_type="cod", call_attempt_count=1, latest_call_result="No Answer", human_action_count=1),
        queue_order("317", payment_type="cod", call_attempt_count=1, latest_call_result="Confirmed", human_action_count=1, operational_status="Ready for Booking"),
    ]
    async def load(_db): return values
    monkeypatch.setattr(routes, "_load_orders", load)
    result = await routes.list_orders(queue="previous", attempt="1", db=None)
    assert [value.order_number for value in result.items] == ["316"]


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


QUEUE_NOW = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)


def test_today_ready_for_booking_remains_fresh() -> None:
    order = queue_order("324687", created_date="2026-08-11T04:30:00Z", payment_type="prepaid", human_action_count=2, operational_status="Ready for Booking")
    assert routes._matches_queue(order, "fresh", QUEUE_NOW)
    assert not routes._matches_queue(order, "previous", QUEUE_NOW)


def test_prior_day_ready_for_booking_uses_safe_fresh_fallback() -> None:
    order = queue_order("324686", created_date="2026-08-10T04:30:00Z", payment_type="prepaid", human_action_count=2, operational_status="Ready for Booking")
    assert routes._matches_queue(order, "fresh", QUEUE_NOW)
    assert not routes._matches_queue(order, "previous", QUEUE_NOW, "follow_up")


def test_fixture_counts_restore_action_semantics_without_mass_migration() -> None:
    sample = [
        queue_order("401", created_date="2026-08-01T04:30:00Z", payment_type="prepaid", human_action_count=0),
        queue_order("402", created_date="2026-08-01T04:30:00Z", payment_type="cod", call_attempt_count=0),
        queue_order("403", created_date="2026-08-11T04:30:00Z", payment_type="cod", call_attempt_count=1, latest_call_result="Busy", human_action_count=1),
        queue_order("404", created_date="2026-08-11T04:30:00Z", payment_type="cod", call_attempt_count=1, latest_call_result="On Hold", human_action_count=1),
        queue_order("405", created_date="2026-08-10T04:30:00Z", payment_type="prepaid", human_action_count=2, operational_status="Ready for Booking"),
        queue_order("406", created_date="2026-08-11T04:30:00Z", payment_type="prepaid", human_action_count=2, operational_status="Ready for Booking"),
    ]
    fresh = [order.order_number for order in sample if routes._matches_queue(order, "fresh", QUEUE_NOW)]
    follow_up = [order.order_number for order in sample if routes._matches_queue(order, "previous", QUEUE_NOW, "follow_up")]
    on_hold = [order.order_number for order in sample if routes._matches_queue(order, "previous", QUEUE_NOW, "on_hold")]
    assert fresh == ["401", "402", "405", "406"]
    assert follow_up == ["403"]
    assert on_hold == ["404"]


def test_booked_label_pending_and_printed_today_are_routed_exclusively() -> None:
    pending = queue_order("324680", shipment={"booking_status": "booked", "awb": "AWB-1", "label_print_status": "not_printed"}, operational_status="Booked")
    printed = queue_order("324681", shipment={"booking_status": "booked", "awb": "AWB-2", "label_print_status": "printed", "label_last_printed_at": "2026-08-11T09:00:00Z"}, operational_status="Booked")
    assert routes._matches_queue(pending, "labels_to_print", QUEUE_NOW)
    assert not routes._matches_queue(pending, "printed_today", QUEUE_NOW)
    assert routes._matches_queue(printed, "printed_today", QUEUE_NOW)
    assert not routes._matches_queue(printed, "labels_to_print", QUEUE_NOW)


@pytest.mark.parametrize(("status", "payment", "result"), [
    ("Call Pending", "cod", None),
    ("Address Verification Pending", "prepaid", None),
    ("Ready for Booking", "prepaid", None),
    ("Needs Review", "cod", "Wrong Number"),
    ("Call Pending", "cod", "Busy"),
    ("Call Pending", "cod", "On Hold"),
])
def test_every_unresolved_order_has_exactly_one_primary_operational_queue(status, payment, result) -> None:
    order = queue_order("324682", created_date="2026-08-10T04:30:00Z", payment_type=payment, latest_call_result=result, call_attempt_count=1 if result else 0, human_action_count=1, operational_status=status)
    membership = [routes._matches_queue(order, "fresh", QUEUE_NOW), routes._matches_queue(order, "previous", QUEUE_NOW, "follow_up"), routes._matches_queue(order, "previous", QUEUE_NOW, "on_hold")]
    assert sum(membership) == 1


def test_primary_actionable_queues_are_mutually_exclusive() -> None:
    orders = [
        queue_order("324683", created_date="2026-08-11T04:30:00Z", operational_status="Ready for Booking"),
        queue_order("324684", created_date="2026-08-10T04:30:00Z", operational_status="Ready for Booking"),
        queue_order("324685", shipment={"booking_status": "booked", "awb": "AWB-3", "label_print_status": "not_printed"}, operational_status="Booked"),
        queue_order("324688", shipment={"booking_status": "booked", "awb": "AWB-4", "label_print_status": "printed", "label_last_printed_at": "2026-08-11T09:00:00Z"}, operational_status="Booked"),
    ]
    for order in orders:
        membership = [
            routes._matches_queue(order, "fresh", QUEUE_NOW),
            routes._matches_queue(order, "previous", QUEUE_NOW, "follow_up") or routes._matches_queue(order, "previous", QUEUE_NOW, "on_hold"),
            routes._matches_queue(order, "labels_to_print", QUEUE_NOW),
            routes._matches_queue(order, "printed_today", QUEUE_NOW),
        ]
        assert sum(membership) == 1


@pytest.mark.anyio
async def test_reconciliation_sets_and_mismatch_classification(monkeypatch):
    os_only = queue_order("201", payment_type="cod", call_attempt_count=0)
    both = queue_order("202", payment_type="prepaid", human_action_count=0)
    stale = queue_order("203", fulfillment_status="fulfilled", operational_status="Shipped")
    async def load(_db): return [os_only, both, stale]
    async def new(_self, force_refresh=False):
        return [
            {"id": 2, "channel_order_id": "202", "status": "NEW"},
            {"id": 3, "channel_order_id": "203", "status": "NEW", "products": [{"status": "CANCELED"}]},
        ]
    async def find(_self, number): return None if number == "201" else {"channel_order_id": number, "status": "NEW"}
    monkeypatch.setattr(routes, "_load_reconciliation_orders", load)
    monkeypatch.setattr(routes.ShiprocketService, "list_new_orders", new)
    monkeypatch.setattr(routes.ShiprocketService, "find_existing_order", find)
    result = await routes._build_reconciliation_summary(db=None)
    assert result["operations_queue"] == 2
    assert result["present_in_both"] == 1
    assert result["missing_in_shiprocket"] == 1
    assert result["only_in_os"] == [{"order_number": "201", "reason": "not yet synced to Shiprocket", "shiprocket_status": None}]
    assert result["only_in_shiprocket"][0]["reason"] == "stale Shiprocket state"
    assert result["duplicate_mapping_anomalies"] == []
    assert [item["order_number"] for item in result["datasets"]["operations"]] == ["201", "202"]
    assert result["datasets"]["cleanup_pending"][0]["reason"] == "stale Shiprocket state"
    assert result["datasets"]["missing_in_shiprocket"][0]["reason"] == "not yet synced to Shiprocket"


@pytest.mark.parametrize("order,expected", [
    (queue_order("316167", created_date="2026-05-14T00:00:00+00:00", fulfillment_status="unfulfilled", cancelled_at=None, shipment=None), True),
    (queue_order("316999", created_date="2026-07-31T00:00:00+00:00", fulfillment_status="unfulfilled", cancelled_at=None, shipment=None), True),
    (queue_order("316998", fulfillment_status="fulfilled", shipment=None), False),
    (queue_order("316997", fulfillment_status="unfulfilled", cancelled_at="2026-05-15T00:00:00+00:00", shipment=None), False),
    (queue_order("316996", fulfillment_status="unfulfilled", shipment={"awb": "AWB1"}), False),
    (queue_order("316995", fulfillment_status="unfulfilled", shipment={"shipment_id": "SHIP1"}), False),
    (queue_order("316994", fulfillment_status="unfulfilled", shipment={"provider_order_id": "QUOTE1", "booking_status": "failed", "selected_courier_id": "3"}), True),
])
def test_reconciliation_requires_active_unfulfilled_without_genuine_booking_evidence(order, expected):
    assert routes._requires_reconciliation_action(order) is expected


@pytest.mark.anyio
async def test_reconciliation_summary_counts_only_actionable_unfulfilled_orders(monkeypatch):
    old = queue_order("316167", created_date="2026-05-14T00:00:00+00:00", fulfillment_status="unfulfilled", shipment=None)
    recent = queue_order("316999", fulfillment_status="unfulfilled", shipment=None)
    fulfilled = queue_order("316998", fulfillment_status="fulfilled", shipment=None)
    cancelled = queue_order("316997", fulfillment_status="unfulfilled", cancelled_at="2026-07-31T00:00:00+00:00", shipment=None)
    booked = queue_order("316996", fulfillment_status="unfulfilled", shipment={"awb": "AWB1"})
    placeholder = queue_order("316995", fulfillment_status="unfulfilled", shipment={"provider_order_id": "FAILED1", "booking_status": "failed"})
    async def load(_db): return [old, recent, fulfilled, cancelled, booked, placeholder]
    async def new(_self, force_refresh=False): return []
    async def find(_self, number): return None
    monkeypatch.setattr(routes, "_load_reconciliation_orders", load)
    monkeypatch.setattr(routes.ShiprocketService, "list_new_orders", new)
    monkeypatch.setattr(routes.ShiprocketService, "find_existing_order", find)

    result = await routes._build_reconciliation_summary(db=None)

    assert result["operations_queue"] == 3
    assert result["missing_in_shiprocket"] == 3
    assert {item["order_number"] for item in result["datasets"]["operations"]} == {"316167", "316999", "316995"}


@pytest.mark.anyio
async def test_reconciliation_returns_last_snapshot_while_background_refresh_runs(monkeypatch):
    snapshot = {
        "data": {"operations_queue": 112, "missing_in_shiprocket": 41},
        "last_refreshed_at": "2026-08-09T00:00:00Z",
        "refresh_error": "Temporary provider error",
    }
    started = []
    monkeypatch.setattr(routes.ReportSnapshotStore, "get", lambda key: snapshot)
    monkeypatch.setattr(routes, "_start_reconciliation_refresh", lambda: started.append(True) or True)

    result = await routes.reconciliation_summary(refresh=True)

    assert result["operations_queue"] == 112
    assert result["refresh_error"] == "Temporary provider error"
    assert started == [True]
