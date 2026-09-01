from datetime import datetime, timezone

import pytest

from app.api.routes import orders as routes
from app.services import order_operations
from app.services.order_operations import OrderOperationsStore
from app.services.shopify import ShopifyService
from tests.test_operations_upgrade import raw_order


def _order(number: str, *, entered_at: str | None) -> object:
    raw = {**raw_order(), "id": int(number), "name": f"#{number}", "order_number": int(number)}
    return ShopifyService._to_order(raw).model_copy(update={
        "order_id": number,
        "order_number": number,
        "payment_type": "cod",
        "call_attempt_count": 1,
        "latest_call_result": "No Answer",
        "human_action_count": 1,
        "previous_pending_entered_at": entered_at,
    })


def test_previous_pending_entry_is_durable_and_updates_on_reentry(monkeypatch, tmp_path):
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "order_operations.json")

    OrderOperationsStore.append_call_log("101", {"result": "No Answer", "timestamp": "2026-09-01T05:00:00+00:00", "operator": "ops"})
    OrderOperationsStore.append_call_log("101", {"result": "Busy", "timestamp": "2026-09-01T06:00:00+00:00", "operator": "ops"})
    assert OrderOperationsStore.get("101")["previous_pending_entered_at"] == "2026-09-01T05:00:00+00:00"

    OrderOperationsStore.append_call_log("101", {"result": "Confirmed", "timestamp": "2026-09-01T07:00:00+00:00", "operator": "ops"})
    OrderOperationsStore.append_call_log("101", {"result": "Callback Requested", "timestamp": "2026-09-01T08:00:00+00:00", "operator": "ops"})
    assert OrderOperationsStore.get("101")["previous_pending_entered_at"] == "2026-09-01T08:00:00+00:00"


def test_previous_pending_sections_use_latest_entry_timestamp_not_order_date():
    now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    carry_forward = _order("201", entered_at="2026-08-31T17:00:00+00:00")
    moved_today = _order("202", entered_at="2026-09-01T05:00:00+00:00")
    reentered_today = _order("203", entered_at="2026-09-01T08:00:00+00:00")

    assert routes._matches_queue(carry_forward, "previous", now)
    assert routes._previous_pending_section(carry_forward, now) == "previous_days"
    assert routes._previous_pending_section(moved_today, now) == "today"
    assert routes._previous_pending_section(reentered_today, now) == "today"


def test_previous_pending_section_honors_ist_midnight_boundary():
    now = datetime(2026, 9, 1, 18, 30, tzinfo=timezone.utc)  # 00:00 IST on Sep 2
    before_midnight = _order("301", entered_at="2026-09-01T18:29:59+00:00")
    at_midnight = _order("302", entered_at="2026-09-01T18:30:00+00:00")

    assert routes._previous_pending_section(before_midnight, now) == "previous_days"
    assert routes._previous_pending_section(at_midnight, now) == "today"


@pytest.mark.anyio
async def test_previous_pending_today_is_newest_first_before_previous_days(monkeypatch):
    fixed_now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    async def load(_db):
        return [
            _order("401", entered_at="2026-08-31T10:00:00+00:00"),
            _order("402", entered_at="2026-09-01T04:00:00+00:00"),
            _order("403", entered_at="2026-09-01T06:00:00+00:00"),
        ]

    monkeypatch.setattr(routes, "datetime", FixedDatetime)
    monkeypatch.setattr(routes, "_load_orders", load)
    page = await routes.list_orders(queue="previous", page_size=20, db=None)

    assert [item.order_number for item in page.items] == ["403", "402", "401"]
    assert page.counts["previous_today"] == 2
    assert page.counts["previous_days"] == 1
