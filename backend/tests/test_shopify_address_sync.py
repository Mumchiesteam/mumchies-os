from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.orders import AddressPayload, update_order_address
from app.db.base import Base
from app.services import order_operations as operations_module
from app.services import shopify as shopify_module
from app.services.shopify import ShopifyService, ShopifySyncError


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class Client:
    def __init__(self, responses, calls):
        self.responses = responses
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

    async def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return self.responses.pop(0)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


def install(monkeypatch, responses):
    calls = []
    monkeypatch.setattr(shopify_module.httpx, "AsyncClient", lambda timeout=20.0: Client(responses, calls))

    async def token(_self):
        return "test-token"

    monkeypatch.setattr(ShopifyService, "_get_access_token", token)
    return calls


def corrected():
    return {
        "customer_name": "Test Customer", "phone": "9999999999", "address_line1": "10 New Road",
        "address_line2": "Floor 2", "landmark": "Clock", "city": "Pune", "state": "Maharashtra", "pincode": "411001",
    }


def test_matching_uses_identifier_before_fields():
    saved = [
        {"id": 1, "address1": "Different"},
        {"id": 2, "address1": "Same", "city": "Pune", "province": "Maharashtra", "zip": "411001"},
    ]
    assert ShopifyService.match_customer_address({"customer_address_id": 1, "address1": "Same"}, saved)["id"] == 1


def test_matching_falls_back_to_normalized_fields():
    original = {"address1": " 10 OLD Road ", "address2": "", "city": "PUNE", "province": "Maharashtra", "zip": "411001", "phone": "+91 99999 99999"}
    saved = [{"id": 7, "address1": "10 old road", "address2": None, "city": "pune", "province": "maharashtra", "zip": "411001", "phone": "9999999999", "default": True}]
    assert ShopifyService.match_customer_address(original, saved)["id"] == 7


@pytest.mark.anyio
async def test_matching_address_is_updated_without_default_mutation(monkeypatch):
    calls = install(monkeypatch, [
        Response({"addresses": [{"id": 7, "address1": "10 Old Road", "address2": None, "city": "Pune", "province": "Maharashtra", "zip": "411001", "phone": "9999999999", "default": True}]}),
        Response({"customer_address": {"id": 7, "default": True}}),
    ])
    result = await ShopifyService(store="shop.test", client_id="id", client_secret="secret", api_version="2025-07").update_customer_address(
        "5", {"address1": "10 Old Road", "city": "Pune", "province": "Maharashtra", "zip": "411001", "phone": "9999999999"}, corrected(), set_as_default=True
    )
    assert result["created"] is False
    assert result["preserved_default"] is True
    assert [call[0] for call in calls] == ["GET", "PUT"]
    assert "/addresses/7.json" in calls[1][1]


@pytest.mark.anyio
async def test_new_address_is_default_only_when_selected(monkeypatch):
    calls = install(monkeypatch, [
        Response({"addresses": []}),
        Response({"customer_address": {"id": 8, "default": False}}),
        Response({"customer_address": {"id": 8, "default": True}}),
    ])
    result = await ShopifyService(store="shop.test", client_id="id", client_secret="secret", api_version="2025-07").update_customer_address(
        "5", {"address1": "Old"}, corrected(), set_as_default=True
    )
    assert result["created"] is True
    assert [call[0] for call in calls] == ["GET", "POST", "PUT"]
    assert calls[2][1].endswith("/addresses/8/default.json")


@pytest.mark.anyio
async def test_customer_failure_does_not_undo_local_or_order_sync(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(operations_module, "OPS_FILE", tmp_path / "operations.json")
    order_updated = False

    async def context(_self, _order_id):
        return {"customer_id": "5", "shipping_address": {"address1": "Old"}}

    async def update_order(_self, _order_id, _address):
        nonlocal order_updated
        order_updated = True

    async def update_customer(*_args, **_kwargs):
        raise ShopifySyncError("Customer update rejected")

    monkeypatch.setattr(ShopifyService, "get_order_address_context", context)
    monkeypatch.setattr(ShopifyService, "update_order_shipping_address", update_order)
    monkeypatch.setattr(ShopifyService, "update_customer_address", update_customer)

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'state.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        result = await update_order_address("order-1", AddressPayload(**corrected()), db)
    finally:
        db.close()
        engine.dispose()

    assert order_updated is True
    assert result["corrected_address"]["address_line1"] == "10 New Road"
    assert result["address_sync_results"]["shopify_order"] == "synced"
    assert result["address_sync_results"]["shopify_customer"] == "failed"


@pytest.mark.anyio
async def test_unlinked_customer_is_not_applicable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(operations_module, "OPS_FILE", tmp_path / "operations.json")

    async def context(_self, _order_id):
        return {"customer_id": None, "shipping_address": {"address1": "Old"}}

    async def update_order(_self, _order_id, _address):
        return None

    monkeypatch.setattr(ShopifyService, "get_order_address_context", context)
    monkeypatch.setattr(ShopifyService, "update_order_shipping_address", update_order)
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'state.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        result = await update_order_address("order-1", AddressPayload(**corrected()), db)
    finally:
        db.close()
        engine.dispose()
    assert result["address_sync_results"]["shopify_customer"] == "not_applicable"
