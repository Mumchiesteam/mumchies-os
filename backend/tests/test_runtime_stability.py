from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.main import health_check
from app.schemas.orders import ShopifyOrder
from app.services.shopify import ShopifyService


def _order(order_id: str, customer_id: str) -> ShopifyOrder:
    return ShopifyOrder(
        order_id=order_id, order_number=order_id, created_date=datetime.now(timezone.utc).isoformat(),
        customer_id=customer_id, products=[], total_amount=Decimal("1"), tags=[],
    )


def test_health_is_constant_time_and_has_no_snapshot_or_provider_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.report_snapshots.ReportSnapshotStore.get", lambda *_: pytest.fail("health read snapshot storage"))
    monkeypatch.setattr("app.services.shipment_poller.poller_status", lambda: pytest.fail("health read poller storage"))
    result = health_check()
    assert result["status"] == "ok"
    assert "rss_mb" in result


def test_shopify_object_caches_are_bounded() -> None:
    now = __import__("time").monotonic() + 60
    ShopifyService._reporting_orders_cache = {
        ("store", "version", str(index), str(index)): (now + index, []) for index in range(10)
    }
    ShopifyService._single_order_cache = {
        ("store", "version", str(index)): (now + index, _order(str(index), str(index))) for index in range(300)
    }
    ShopifyService._prune_caches()
    assert len(ShopifyService._reporting_orders_cache) <= 2
    assert len(ShopifyService._single_order_cache) <= 128


@pytest.mark.anyio
async def test_repeat_history_retains_at_most_one_prior_row_per_requested_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    orders = [_order(str(index), str(index)) for index in range(100)]
    nodes = []
    for repeat in range(20):
        for index in range(100):
            nodes.append({
                "id": f"gid://shopify/Order/prior-{repeat}-{index}", "cancelledAt": None,
                "customer": {"id": f"gid://shopify/Customer/{index}"}, "fulfillments": [{"id": "fulfilled"}],
            })

    class Response:
        status_code = 200
        headers: dict[str, str] = {}
        def raise_for_status(self) -> None: return None
        def json(self) -> dict: return {"data": {"orders": {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}}

    service = ShopifyService("store", "id", "secret", "2025-07")
    async def graphql(_query, _variables):
        return {"orders": {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}
    monkeypatch.setattr(service, "graphql", graphql)
    retained = await service._repeat_history_rows(orders)
    assert len(retained) == len(orders)
    await service._enrich_repeat_customer_history(orders)
    assert all(order.customer_orders_count == 2 for order in orders)


@pytest.mark.anyio
async def test_streaming_backfill_yields_provider_pages_instead_of_one_full_period(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, order_id: str, link: str | None = None):
            self.order_id = order_id; self.headers = {"link": link} if link else {}
        def raise_for_status(self) -> None: return None
        def json(self) -> dict: return {"orders": [{"id": self.order_id, "name": self.order_id, "created_at": "2026-08-21T00:00:00Z", "line_items": []}]}
    class Client:
        def __init__(self): self.responses = [Response("1", '<next>; rel="next"'), Response("2")]
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def get(self, *_args, **_kwargs): return self.responses.pop(0)
    service = ShopifyService("store", "id", "secret", "2025-07")
    monkeypatch.setattr(service, "_get_access_token", lambda: __import__("asyncio").sleep(0, result="token"))
    monkeypatch.setattr("app.services.shopify.httpx.AsyncClient", lambda timeout: Client())
    pages = [page async for page in service.iter_orders_created_between(datetime.now(timezone.utc) - timedelta(days=90), datetime.now(timezone.utc))]
    assert [[order.order_id for order in page] for page in pages] == [["1"], ["2"]]
