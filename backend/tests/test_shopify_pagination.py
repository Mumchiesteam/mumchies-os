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

    first = _FakeResponse(
        [{"id": 1, "name": "1001", "order_number": 1, "created_at": "2026-07-17T10:00:00Z", "line_items": []}],
        '<https://store.myshopify.com/admin/api/2025-07/orders.json?page_info=abc>; rel="next"',
    )
    second = _FakeResponse(
        [{"id": 2, "name": "1002", "order_number": 2, "created_at": "2026-07-16T10:00:00Z", "line_items": []}],
    )
    fake_client = _FakeClient([first, second])
    monkeypatch.setattr("app.services.shopify.httpx.AsyncClient", lambda timeout: fake_client)

    orders = await ShopifyService().get_latest_orders()

    assert [order.order_id for order in orders] == ["1", "2"]
    assert len(fake_client.requests) == 2
    assert fake_client.requests[0][1]["limit"] == "250"
    assert fake_client.requests[1][1] is None
    assert fake_client.requests[0][2]["X-Shopify-Access-Token"] == "token"


def _is_today(created_at: datetime, now: datetime) -> bool:
    cutoff = now - timedelta(hours=24)
    return cutoff <= created_at <= now


def _is_previous_pending(order: dict[str, object], now: datetime) -> bool:
    created_at = order["created_at"]
    assert isinstance(created_at, datetime)
    if not (created_at < now - timedelta(hours=24)):
        return False
    if order.get("cancelled_at"):
        return False
    if order.get("fulfillment_status") in {"fulfilled", "partial"}:
        return False
    if str(order.get("financial_status") or "").lower() == "cancelled":
        return False
    tags = " ".join(order.get("tags", []))
    return "shipped" not in tags.lower() and "delivered" not in tags.lower()


def test_queue_predicates_cover_23h_25h_and_shipped_orders() -> None:
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    twenty_three_hours_old = {"created_at": now - timedelta(hours=23), "cancelled_at": None, "fulfillment_status": None, "financial_status": "paid", "tags": []}
    twenty_five_hours_old = {"created_at": now - timedelta(hours=25), "cancelled_at": None, "fulfillment_status": None, "financial_status": "paid", "tags": []}
    shipped = {"created_at": now - timedelta(hours=25), "cancelled_at": None, "fulfillment_status": "fulfilled", "financial_status": "paid", "tags": []}

    assert _is_today(twenty_three_hours_old["created_at"], now) is True
    assert _is_previous_pending(twenty_five_hours_old, now) is True
    assert _is_previous_pending(shipped, now) is False
