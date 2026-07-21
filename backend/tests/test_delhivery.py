from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.api.routes.couriers import PackageDetailsPayload, _build_delhivery_payload
from app.api.routes.orders import router as orders_router
from app.db.session import get_db
from app.repositories.shiprocket import get_shipment, upsert_shipment
from app.schemas.orders import OrderProduct, ShippingAddress, ShopifyOrder
from app.services import delhivery as module
from app.services.delhivery import DelhiveryError, DelhiveryService, shadowfax_zone_d_quote


class Response:
    def __init__(self, payload=None, status_code=200, *, content=b"", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._payload


class Client:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture()
def sqlite_session(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'delhivery.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def install(monkeypatch, responses):
    client = Client(responses)
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_kwargs: client)
    return client


def shipment_payload(payment_mode="Prepaid"):
    return {
        "name": "Test Customer", "add": "Test address", "pin": "144001", "city": "Jalandhar",
        "state": "Punjab", "country": "India", "phone": "9999999999", "order": "322700",
        "payment_mode": payment_mode, "cod_amount": 500 if payment_mode == "COD" else 0,
        "total_amount": 500, "products_desc": "Test product", "quantity": 1, "weight": 950,
        "shipment_width": 5, "shipment_length": 5, "shipment_height": 5, "shipping_mode": "Surface",
    }


def shopify_order(postcode="144001"):
    return ShopifyOrder(
        order_id="1", order_number="322700", created_date="2026-07-21T10:00:00+00:00",
        customer_name="Test Customer", phone="9999999999", email=None,
        shipping_address=ShippingAddress(name="Test Customer", address="10 Road", landmark=None, city="Pune", state="Maharashtra", pincode=postcode),
        products=[OrderProduct(product_name="Test Product", sku="SKU1", quantity=1, weight_grams=950, price=500)],
        total_amount=500, payment_status="paid", tags=[],
    )


@pytest.mark.anyio
async def test_configured_direct_delhivery_rate_is_bookable(monkeypatch):
    install(monkeypatch, [
        Response({"delivery_codes": [{"postal_code": {"cod": "Y", "pre_paid": "Y"}}]}),
        Response([{"total_amount": 120, "charge_COD": 20, "mode": "Surface", "tat": 4}]),
    ])
    quote = (await DelhiveryService(token="token", pickup="Mumchies Foods").serviceability("560076", "144529", 0.95, True))[0]
    assert (quote.rate, quote.cod_charge, quote.total_estimated_shipping_cost) == (100, 20, 120)
    assert quote.booking_supported is True


def test_missing_configuration_disables_only_direct_delhivery(monkeypatch):
    monkeypatch.setattr(module.settings, "delhivery_token", None)
    monkeypatch.setattr(module.settings, "delhivery_pickup", None)
    assert DelhiveryService().configured is False


@pytest.mark.anyio
@pytest.mark.parametrize("payment_mode", ["Prepaid", "COD"])
async def test_prepaid_and_cod_booking_persist(monkeypatch, sqlite_session, payment_mode):
    client = install(monkeypatch, [
        Response({"ShipmentData": []}),
        Response({"success": True, "packages": [{"waybill": "WB1", "status": "Success"}]}),
    ])
    service = DelhiveryService(token="token", pickup="Mumchies Foods")
    result = await service.book_order_shipment(
        sqlite_session, "local-1", "322700", shipment_payload(payment_mode),
        {"weight_kg": .95, "length_cm": 5, "breadth_cm": 5, "height_cm": 5},
        "delhivery:surface", "Delhivery Surface",
    )
    stored = get_shipment(sqlite_session, "local-1")
    assert result["existing"] is False
    assert (stored.provider, stored.awb, stored.booking_status) == ("delhivery", "WB1", "booked")
    manifest = json.loads(client.calls[1][2]["data"]["data"])
    assert manifest["pickup_location"]["name"] == "Mumchies Foods"
    assert manifest["shipments"][0]["payment_mode"] == payment_mode
    assert "waybill" not in manifest["shipments"][0]


@pytest.mark.anyio
async def test_duplicate_local_shipment_never_calls_provider(monkeypatch, sqlite_session):
    client = install(monkeypatch, [])
    upsert_shipment(sqlite_session, "local-1", provider="delhivery", provider_order_id="322700", awb="WB1")
    result = await DelhiveryService(token="token", pickup="Mumchies Foods").book_order_shipment(
        sqlite_session, "local-1", "322700", shipment_payload(), {}, "delhivery:surface", "Delhivery Surface"
    )
    assert result["existing"] is True
    assert client.calls == []


@pytest.mark.anyio
async def test_duplicate_upstream_shipment_is_reconciled(monkeypatch, sqlite_session):
    install(monkeypatch, [
        Response({"ShipmentData": [{"Shipment": {"AWB": "WB2", "ReferenceNo": "322700", "Status": {"Status": "Manifested"}}}]}),
        Response({"ShipmentData": [{"Shipment": {"AWB": "WB2", "ReferenceNo": "322700", "Status": {"Status": "Manifested"}}}]}),
    ])
    result = await DelhiveryService(token="token", pickup="Mumchies Foods").book_order_shipment(
        sqlite_session, "local-1", "322700", shipment_payload(), {}, "delhivery:surface", "Delhivery Surface"
    )
    assert result["existing"] is True
    assert get_shipment(sqlite_session, "local-1").awb == "WB2"


@pytest.mark.anyio
async def test_partial_success_persists_recoverable_identifiers(monkeypatch, sqlite_session):
    install(monkeypatch, [
        Response({"ShipmentData": []}),
        Response({"success": False, "packages": [{"waybill": "WB3", "status": "Failure", "remarks": "Incomplete"}]}),
        Response({"ShipmentData": []}),
    ])
    with pytest.raises(DelhiveryError, match="Incomplete"):
        await DelhiveryService(token="token", pickup="Mumchies Foods").book_order_shipment(
            sqlite_session, "local-1", "322700", shipment_payload(), {}, "delhivery:surface", "Delhivery Surface"
        )
    stored = get_shipment(sqlite_session, "local-1")
    assert (stored.awb, stored.booking_status) == ("WB3", "manifest_partial")


@pytest.mark.anyio
async def test_provider_rejection_is_safe(monkeypatch):
    install(monkeypatch, [Response({"message": "Invalid pickup"}, 400)])
    with pytest.raises(DelhiveryError, match="Invalid pickup") as exc:
        await DelhiveryService(token="token", pickup="Mumchies Foods").create_shipment(shipment_payload())
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_tracking_is_normalized(monkeypatch):
    install(monkeypatch, [Response({"ShipmentData": [{"Shipment": {"AWB": "WB1", "ReferenceNo": "322700", "Status": {"Status": "In Transit"}}}]})])
    result = await DelhiveryService(token="token", pickup="Mumchies Foods").tracking("WB1")
    assert result["status"] == "In Transit"
    assert result["tracking_url"].endswith("/WB1")


@pytest.mark.anyio
async def test_timeout_after_upstream_success_is_reconciled(monkeypatch, sqlite_session):
    install(monkeypatch, [
        Response({"ShipmentData": []}),
        __import__("httpx").ReadTimeout("manifest timed out"),
        Response({"ShipmentData": [{"Shipment": {"AWB": "WB9", "ReferenceNo": "322700", "Status": {"Status": "Manifested"}}}]}),
    ])
    result = await DelhiveryService(token="token", pickup="Mumchies Foods").book_order_shipment(
        sqlite_session, "local-timeout", "322700", shipment_payload(),
        {"weight_kg": .95, "length_cm": 5, "breadth_cm": 5, "height_cm": 5},
        "delhivery:surface", "Delhivery Surface",
    )
    assert result["reconciled_after_timeout"] is True
    assert get_shipment(sqlite_session, "local-timeout").awb == "WB9"


@pytest.mark.anyio
async def test_shiprocket_booked_order_blocks_direct_delhivery(monkeypatch, sqlite_session):
    install(monkeypatch, [])
    upsert_shipment(sqlite_session, "local-shiprocket", provider="shiprocket", provider_order_id="322700", awb="SR1")
    with pytest.raises(DelhiveryError, match="already booked with shiprocket"):
        await DelhiveryService(token="token", pickup="Mumchies Foods").book_order_shipment(
            sqlite_session, "local-shiprocket", "322700", shipment_payload(), {},
            "delhivery:surface", "Delhivery Surface",
        )


@pytest.mark.anyio
async def test_label_direct_pdf_bytes_are_unchanged(monkeypatch):
    original = b"%PDF-1.4\nprovider-original"
    client = install(monkeypatch, [Response(None, content=original, headers={"content-type": "application/pdf"})])
    result = await DelhiveryService(token="token", pickup="Mumchies Foods").label("WB1")
    assert result.content == original
    assert client.calls[0][2]["params"]["pdf"] == "True"


@pytest.mark.anyio
async def test_label_detects_pdf_signature_with_wrong_content_type(monkeypatch):
    original = b"%PDF-1.7\nprovider-original"
    install(monkeypatch, [Response(None, content=original, headers={"content-type": "application/octet-stream"})])
    result = await DelhiveryService(token="token", pickup="Mumchies Foods").label("WB1")
    assert result.content == original


@pytest.mark.anyio
async def test_label_downloads_official_url_without_forwarding_token(monkeypatch):
    url = "https://express-hq-prod.s3.ap-south-1.amazonaws.com/packing-slip/WB1.pdf"
    original = b"%PDF-1.4\nofficial-s3-bytes"
    client = install(monkeypatch, [
        Response({"packages": [{"pdf_download_link": url}]}),
        Response(None, content=original, headers={"content-type": "application/pdf"}),
    ])
    result = await DelhiveryService(token="secret-token", pickup="Mumchies Foods").label("WB1")
    assert result.content == original
    assert client.calls[1][1] == url
    assert "Authorization" not in client.calls[1][2].get("headers", {})


@pytest.mark.anyio
async def test_label_supports_nested_official_url(monkeypatch):
    url = "https://express-hq-prod.s3.ap-south-1.amazonaws.com/packing-slip/WB1.pdf"
    install(monkeypatch, [
        Response({"data": {"documents": [{"label": {"document_url": url}}]}}),
        Response(None, content=b"%PDF-1.4\nnested", headers={"content-type": "application/pdf"}),
    ])
    result = await DelhiveryService(token="token", pickup="Mumchies Foods").label("WB1")
    assert result.content == b"%PDF-1.4\nnested"


@pytest.mark.anyio
async def test_label_rejects_non_delhivery_url(monkeypatch):
    install(monkeypatch, [Response({"packages": [{"pdf_download_link": "https://evil.example/label.pdf"}]})])
    with pytest.raises(DelhiveryError, match="not enabled"):
        await DelhiveryService(token="token", pickup="Mumchies Foods").label("WB1")


@pytest.mark.anyio
async def test_label_unauthorized_is_normalized(monkeypatch):
    install(monkeypatch, [Response({"detail": "Unauthorized"}, status_code=401)])
    with pytest.raises(DelhiveryError, match="not enabled") as exc:
        await DelhiveryService(token="token", pickup="Mumchies Foods").label("WB1")
    assert exc.value.status_code == 401


@pytest.mark.anyio
async def test_label_capability_missing_is_normalized(monkeypatch):
    install(monkeypatch, [Response({"packages": [{"wbn": "WB1"}]})])
    with pytest.raises(DelhiveryError, match="not enabled"):
        await DelhiveryService(token="token", pickup="Mumchies Foods").label("WB1")


@pytest.mark.anyio
async def test_label_empty_packages_reports_unmanifested(monkeypatch):
    install(monkeypatch, [Response({"packages": []}, content=b'{}')])
    with pytest.raises(DelhiveryError, match="unmanifested"):
        await DelhiveryService(token="token", pickup="Mumchies Foods").label("WB1")


def test_provider_label_endpoint_requires_awb(sqlite_session):
    upsert_shipment(sqlite_session, "missing-awb", provider="delhivery", booking_status="booked")
    app = FastAPI()
    app.include_router(orders_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: sqlite_session
    response = TestClient(app).get("/api/v1/orders/missing-awb/shipment/label")
    assert response.status_code == 404
    assert response.json()["detail"] == "No AWB exists for this shipment."


def test_provider_label_endpoint_rejects_unmanifested_shipment(sqlite_session):
    upsert_shipment(sqlite_session, "pending", provider="delhivery", awb="WB1", booking_status="manifest_partial")
    app = FastAPI()
    app.include_router(orders_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: sqlite_session
    response = TestClient(app).get("/api/v1/orders/pending/shipment/label")
    assert response.status_code == 409


def test_provider_label_endpoint_proxies_exact_official_bytes(monkeypatch, sqlite_session):
    original = b"%PDF-1.7\nexact-provider-content"
    upsert_shipment(
        sqlite_session, "booked", provider="delhivery", provider_order_id="322700",
        shipment_id="WB1", awb="WB1", booking_status="booked",
    )

    async def official_label(_self, _awb):
        return Response(None, content=original, headers={"content-type": "application/pdf"})

    monkeypatch.setattr(DelhiveryService, "label", official_label)
    app = FastAPI()
    app.include_router(orders_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: sqlite_session
    response = TestClient(app).get("/api/v1/orders/booked/shipment/label")
    assert response.status_code == 200
    assert response.content == original
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == 'attachment; filename="delhivery-322700-WB1.pdf"'

    inline_response = TestClient(app).get("/api/v1/orders/booked/shipment/label?disposition=inline")
    assert inline_response.status_code == 200
    assert inline_response.content == original
    assert inline_response.headers["content-disposition"] == 'inline; filename="delhivery-322700-WB1.pdf"'


@pytest.mark.anyio
async def test_cancellation_contract(monkeypatch):
    client = install(monkeypatch, [Response({"status": True})])
    result = await DelhiveryService(token="token", pickup="Mumchies Foods").cancel("WB1")
    assert result["status"] is True
    assert client.calls[0][2]["json"]["cancellation"] == "true"


def test_shadowfax_zone_d_is_unchanged():
    quote = shadowfax_zone_d_quote(True)
    assert quote["rate"] == 59
    assert quote["booking_supported"] is False


def test_missing_postcode_blocks_delhivery_payload():
    with pytest.raises(Exception, match="postcode"):
        _build_delhivery_payload(shopify_order(None), {}, PackageDetailsPayload(weight_kg=.95))


def test_invalid_postcode_blocks_delhivery_payload():
    with pytest.raises(Exception, match="exactly 6 digits"):
        _build_delhivery_payload(shopify_order("14400A"), {}, PackageDetailsPayload(weight_kg=.95))


def test_missing_optional_landmark_does_not_block_delhivery_payload():
    payload = _build_delhivery_payload(shopify_order(), {}, PackageDetailsPayload(weight_kg=.95))
    assert payload["pin"] == "144001"
    assert payload["add"] == "10 Road"
