from datetime import datetime, timezone

from app.api.routes.ndr import _india_day_bounds


def test_india_day_bounds_cross_previous_utc_date():
    start, end = _india_day_bounds(datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc))
    assert start.isoformat() == "2026-08-26T18:30:00+00:00"
    assert end.isoformat() == "2026-08-27T18:30:00+00:00"
