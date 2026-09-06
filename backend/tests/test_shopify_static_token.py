import pytest

from app.core.config import settings
from app.services.shopify import ShopifyService


@pytest.mark.anyio
async def test_static_token_configuration_is_used_without_oauth_token_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "shopify_store", None)
    monkeypatch.setattr(settings, "shopify_store_url", "https://mumchies.example/")
    monkeypatch.setattr(settings, "shopify_token", "static-read-token")
    monkeypatch.setattr(settings, "shopify_client_id", None)
    monkeypatch.setattr(settings, "shopify_client_secret", None)
    monkeypatch.setattr(settings, "shopify_api_version", "2026-07")

    service = ShopifyService()

    assert service.store == "mumchies.example"
    assert await service._get_access_token() == "static-read-token"
