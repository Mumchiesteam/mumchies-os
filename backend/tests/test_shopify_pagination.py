from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import services
from app.services.shopify import ShopifyService


class _FakeResponse:
    def __init__(self, orders: list[dict[str, object]], link: str | None = None) -> None:
        self._orders = orders
        self.headers = {"link": link} if link else {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"orders": self._orders}


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, object, object]] = []

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    async def get(self, url: str, params=None, headers=None):  # noqa: ANN001
        self.requests.append((url, params, headers))
        return self.responses.pop(0)


@pytest.mark.anyio
async def test_shopify_service_follows_link_header_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services.shopify.settings, "shopify_store", "store.myshopify.com")
    monkeypatch.setattr(services.shopify.settings, "shopify_client_id", "client-id")
    monkeypatch.setattr(services.shopify.settings, "shopify_client_secret", "client-secret")
    monkeypatch.setattr(services.shopify.settings, "shopify_api_version", "2025-07")
    monkeypatch.setattr(ShopifyService, "_get_access_token", lambda self: __import__("asyncio").sleep(0, result="token"))

    recent = datetime.now(timezone.utc)
    first = _FakeResponse(
        [{"id": 1, "name": "1001", "order_number": 1, "created_at": recent.isoformat(), "line_items": []}],
        '<https://store.myshopify.com/admin/api/2025-07/orders.json?page_info=abc>; rel="next"',
    )
    second = _FakeResponse(
        [{"id": 2, "name": "1002", "order_number": 2, "created_at": (recent - timedelta(days=1)).isoformat(), "line_items": []}],
    )
    fake_client = _FakeClient([first, second])
    monkeypatch.setattr("app.services.shopify.httpx.AsyncClient", lambda timeout: fake_client)
    monkeypatch.setattr(ShopifyService, "_enrich_repeat_customer_history", lambda self, orders: __import__("asyncio").sleep(0))

    orders = await ShopifyService().get_latest_orders()

    assert [order.order_id for order in orders] == ["1", "2"]
    assert len(fake_client.requests) == 2
    assert fake_client.requests[0][1]["limit"] == "250"
    assert "created_at_min" in fake_client.requests[0][1]
    assert fake_client.requests[1][1] is None
    assert fake_client.requests[0][2]["X-Shopify-Access-Token"] == "token"


@pytest.mark.anyio
async def test_unfulfilled_reconciliation_query_has_no_date_cutoff_and_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services.shopify.settings, "shopify_store", "store.myshopify.com")
    monkeypatch.setattr(services.shopify.settings, "shopify_client_id", "client-id")
    monkeypatch.setattr(services.shopify.settings, "shopify_client_secret", "client-secret")
    monkeypatch.setattr(services.shopify.settings, "shopify_api_version", "2025-07")
    monkeypatch.setattr(ShopifyService, "_get_access_token", lambda self: __import__("asyncio").sleep(0, result="token"))
    first = _FakeResponse(
        [{"id": 1, "name": "316999", "created_at": "2026-07-31T10:00:00Z", "line_items": []}],
        '<https://store.myshopify.com/admin/api/2025-07/orders.json?page_info=older>; rel="next"',
    )
    second = _FakeResponse(
        [{"id": 2, "name": "316167", "created_at": "2026-05-14T10:00:00Z", "line_items": []}],
    )
    fake_client = _FakeClient([first, second])
    monkeypatch.setattr("app.services.shopify.httpx.AsyncClient", lambda timeout: fake_client)

    orders = await ShopifyService().get_active_unfulfilled_orders()

    assert [order.order_number for order in orders] == ["316999", "316167"]
    assert fake_client.requests[0][1]["fulfillment_status"] == "unfulfilled"
    assert "created_at_min" not in fake_client.requests[0][1]
    assert fake_client.requests[1][1] is None
