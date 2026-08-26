from decimal import Decimal

import pytest

from app.schemas.orders import ShopifyOrder
from app.services.shopify import ShopifyService


def order(number: int, customer_id: str | None = None) -> ShopifyOrder:
    return ShopifyOrder(order_id=str(number), order_number=str(number), created_date="2026-08-22T00:00:00Z", customer_id=customer_id, products=[], total_amount=Decimal("1"), tags=[])


@pytest.mark.anyio
async def test_repeat_history_is_batched_not_n_plus_one(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []

    async def graphql(_self, _query, variables):
        calls.append(variables)
        return {"orders": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}

    monkeypatch.setattr(ShopifyService, "graphql", graphql)
    rows = [order(value, str(value)) for value in range(501)]
    assert await ShopifyService()._repeat_history_rows(rows) == []
    assert len(calls) == 3
