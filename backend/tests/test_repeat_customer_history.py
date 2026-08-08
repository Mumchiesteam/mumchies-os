from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.schemas.orders import ShopifyOrder
from app.services.shopify import ShopifyService


def order(*, order_id: str = "current", customer_id: str | None = "7", email: str | None = None, phone: str | None = None) -> ShopifyOrder:
    return ShopifyOrder(
        order_id=order_id, order_number=order_id, created_date=datetime.now(timezone.utc).isoformat(),
        customer_id=customer_id, email=email, phone=phone, products=[], total_amount=Decimal("1"), tags=[],
    )


def history(*, order_id: str, days_ago: int, customer_id: str | None = "7", email: str | None = None, phone: str | None = None, cancelled: bool = False) -> dict[str, object]:
    return {
        "id": f"gid://shopify/Order/{order_id}",
        "createdAt": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
        "cancelledAt": datetime.now(timezone.utc).isoformat() if cancelled else None,
        "email": email, "phone": phone,
        "customer": {"id": f"gid://shopify/Customer/{customer_id}", "email": email, "phone": phone} if customer_id else None,
        "fulfillments": [],
    }


@pytest.mark.anyio
@pytest.mark.parametrize("days_ago", [5, 65])
async def test_prior_order_inside_or_outside_orders_window_marks_repeat(monkeypatch: pytest.MonkeyPatch, days_ago: int) -> None:
    service = ShopifyService("store", "id", "secret", "2025-07")
    current = order()
    monkeypatch.setattr(service, "_repeat_history_rows", lambda orders: __import__("asyncio").sleep(0, result=[history(order_id="prior", days_ago=days_ago), history(order_id="current", days_ago=0)]))
    await service._enrich_repeat_customer_history([current])
    assert current.customer_orders_count == 2


@pytest.mark.anyio
async def test_current_order_does_not_count_as_previous(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ShopifyService("store", "id", "secret", "2025-07")
    current = order()
    monkeypatch.setattr(service, "_repeat_history_rows", lambda orders: __import__("asyncio").sleep(0, result=[history(order_id="current", days_ago=0)]))
    await service._enrich_repeat_customer_history([current])
    assert current.customer_orders_count == 1


@pytest.mark.anyio
async def test_cancelled_before_dispatch_prior_order_is_not_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ShopifyService("store", "id", "secret", "2025-07")
    current = order()
    monkeypatch.setattr(service, "_repeat_history_rows", lambda orders: __import__("asyncio").sleep(0, result=[history(order_id="prior", days_ago=65, cancelled=True)]))
    await service._enrich_repeat_customer_history([current])
    assert current.customer_orders_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("current", "previous"),
    [
        (order(customer_id=None, email=" Person@Example.com "), history(order_id="email", days_ago=65, customer_id=None, email="person@example.com")),
        (order(customer_id=None, phone="+91 98765-43210"), history(order_id="phone", days_ago=65, customer_id=None, phone="09876543210")),
    ],
)
async def test_email_and_phone_fallback(monkeypatch: pytest.MonkeyPatch, current: ShopifyOrder, previous: dict[str, object]) -> None:
    service = ShopifyService("store", "id", "secret", "2025-07")
    monkeypatch.setattr(service, "_repeat_history_rows", lambda orders: __import__("asyncio").sleep(0, result=[previous]))
    await service._enrich_repeat_customer_history([current])
    assert current.customer_orders_count == 2
