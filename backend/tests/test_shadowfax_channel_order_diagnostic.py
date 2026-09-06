from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.services.shadowfax_diagnostics import shadowfax_shopify_order_diagnostic


@pytest.mark.anyio
async def test_shadowfax_channel_diagnostic_resolves_one_matching_shopify_row_without_direct_create(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/login/":
            return httpx.Response(200, json={"token": "channel-token"})
        if request.url.path == "/api/v2/shopify/orders/":
            assert json.loads(request.content) == {
                "page": 1, "limit": 250, "status": "all", "order_start_date": None, "order_end_date": None,
                "shopify_order_id": "326841", "payment_type": None,
            }
            return httpx.Response(200, json={"data": [{
                "id": "6902274883662", "name": "#326841", "status": "NEW", "payment_mode": "Prepaid", "awb_number": None, "platform": "shopify",
            }]})
        pytest.fail(f"Unexpected Shadowfax endpoint: {request.url}")

    monkeypatch.setattr(settings, "shadowfax_email", "ops@example.test")
    monkeypatch.setattr(settings, "shadowfax_password_secret", "not-a-real-password")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://shadowfax360.in")
    try:
        result = await shadowfax_shopify_order_diagnostic(
            shopify_order_id="6902274883662", order_number="326841", shopify_name="#326841", client=client,
        )
    finally:
        await client.aclose()

    assert result["resolver_result"] == {
        "found": True,
        "reason": "matched uniquely",
        "matched_shadowfax_channel_row_id": "6902274883662",
        "shopify_internal_order_id": "6902274883662",
        "client_order_reference": "#326841",
        "status": "NEW",
        "awb": None,
    }
    assert calls == ["/api/v1/login/", "/api/v2/shopify/orders/"]
    assert "/api/v3/clients/orders/" not in calls


@pytest.mark.anyio
async def test_shadowfax_channel_diagnostic_surfaces_sanitized_upstream_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "shadowfax_email", None)
    monkeypatch.setattr(settings, "shadowfax_password_secret", None)
    monkeypatch.setattr(settings, "shadowfax_api_token", "read-only-test-token")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"error": "validation_error", "message": "Invalid Shopify order ID", "validation": {"shopify_order_id": ["invalid"]}})
        )
    )
    try:
        result = await shadowfax_shopify_order_diagnostic(
            shopify_order_id="6917185798222", order_number="326878", shopify_name="#326878", client=client,
        )
    finally:
        await client.aclose()

    assert result["http_status"] == 400
    assert result["search_order_number"] == "326878"
    assert result["provider_error"] == {
        "error": "validation_error", "message": "Invalid Shopify order ID", "validation": {"shopify_order_id": ["invalid"]},
    }
    assert result["resolver_result"]["found"] is False


@pytest.mark.anyio
async def test_shadowfax_channel_diagnostic_fails_closed_for_reference_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "shadowfax_email", None)
    monkeypatch.setattr(settings, "shadowfax_password_secret", None)
    monkeypatch.setattr(settings, "shadowfax_api_token", "read-only-test-token")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "6902274883662", "name": "#different"}]})))
    try:
        result = await shadowfax_shopify_order_diagnostic(
            shopify_order_id="6902274883662", order_number="326841", shopify_name="#326841", client=client,
        )
    finally:
        await client.aclose()

    assert result["resolver_result"]["found"] is False
    assert result["rows"][0]["reason"] == "rejected: client/order reference does not match"
