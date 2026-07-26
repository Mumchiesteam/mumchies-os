from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO

import pytest
import httpx
from fastapi import HTTPException
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.repositories.shiprocket import get_shipment, upsert_shipment
from app.services import order_operations
from app.services.courier_platform import (
    BookingConfidence, LabelFormat, NormalizedShipmentStatus, ProviderConfigurationError,
    ProviderError, ReconciliationStatus, ShadowfaxAdapter, courier_registry,
)
from app.services.courier_platform.service import CourierPlatformService
from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport
from app.services.courier_platform.webhooks import WebhookHandler, process_webhook, webhook_registry
from app.services.courier_platform.models import TrackingResult
from app.services.label_printing import LabelPrintError, LabelService, confirm_batch, create_batch, image_label_to_pdf, print_ready_pdf
from app.api.routes.couriers import PackageDetailsPayload, _build_provider_booking_request
from app.schemas.orders import OrderProduct, ShippingAddress, ShopifyOrder


def exact_pdf(width: int = 288, height: int = 432) -> bytes:
    output = BytesIO(); document = canvas.Canvas(output, pagesize=(width, height))
    document.drawString(20, 20, "provider label"); document.showPage(); document.save()
    return output.getvalue()


def official_booking_payload() -> dict:
    return {
        "order_type": "warehouse",
        "order_details": {"client_order_id": "STAGE-1", "product_value": 500, "payment_mode": "Prepaid", "cod_amount": 0},
        "customer_details": {"name": "Test", "contact": "9999999999", "address_line_1": "Test", "city": "Bengaluru", "state": "Karnataka", "pincode": 560077},
        "pickup_details": {"contact": "9999999999", "address_line_1": "Test", "city": "Bengaluru", "state": "Karnataka", "pincode": 560077},
        "rto_details": {"name": "Test", "contact": "9999999999", "address_line_1": "Test", "city": "Bengaluru", "state": "Karnataka", "pincode": 560077},
        "product_details": [{"sku_name": "Test item", "price": 500}],
    }


@pytest.mark.anyio
async def test_shadowfax_booking_payload_uses_shopify_package_operator_and_warehouse_configuration(monkeypatch):
    async def pickup_location(_self):
        return {
            "pickup_location": "Mumchies Warehouse",
            "name": "Mumchies Foods",
            "phone": "9876543210",
            "address": "10 Factory Road",
            "address_2": "Industrial Area",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pin_code": "560077",
        }

    monkeypatch.setattr("app.api.routes.couriers.ShiprocketService.pickup_location_details", pickup_location)
    order = ShopifyOrder(
        order_id="gid-1", order_number="323999", created_date="2026-07-27T00:00:00Z",
        customer_name="Customer Name", phone="9999999999", email="customer@example.com",
        shipping_address=ShippingAddress(name="Customer Name", address="12 Main Road", landmark="Near Park", city="Delhi", state="Delhi", pincode="110001"),
        products=[OrderProduct(product_name="Cookies", sku="COOKIE-1", quantity=2, weight_grams=250, price=Decimal("250"))],
        total_amount=Decimal("500"), order_total=Decimal("500"), cod_collectable_amount=Decimal("500"),
        payment_type="cod", tags=[],
    )
    payload = await _build_provider_booking_request(
        order, {}, PackageDetailsPayload(weight_kg=0.5, length_cm=20, breadth_cm=15, height_cm=10)
    )
    assert payload["order_type"] == "warehouse"
    assert payload["order_details"] == {
        "client_order_id": "323999", "client_name": "Customer Name", "actual_weight": 500, "volumetric_weight": 600,
        "product_value": 500.0, "payment_mode": "COD", "cod_amount": 500.0,
        "total_amount": 500.0, "order_service": "regular",
    }
    assert payload["customer_details"] == {
        "name": "Customer Name", "contact": "9999999999", "address_line_1": "12 Main Road",
        "address_line_2": "Near Park", "city": "Delhi", "state": "Delhi", "pincode": 110001,
    }
    expected_warehouse = {
        "name": "Mumchies Foods", "contact": "9876543210", "address_line_1": "10 Factory Road",
        "address_line_2": "Industrial Area", "city": "Bengaluru", "state": "Karnataka",
        "pincode": 560077, "unique_code": "Mumchies Warehouse",
    }
    assert payload["pickup_details"] == expected_warehouse
    assert payload["rto_details"] == expected_warehouse
    assert payload["product_details"] == [{"sku_name": "Cookies", "sku_id": "COOKIE-1", "price": 250.0, "additional_details": {"quantity": 2}}]


@pytest.mark.anyio
async def test_shadowfax_booking_payload_rejects_missing_client_name(monkeypatch):
    async def pickup_location(_self):
        return {
            "pickup_location": "Mumchies Warehouse", "name": "Mumchies Foods", "phone": "9876543210",
            "address": "10 Factory Road", "city": "Bengaluru", "state": "Karnataka", "pin_code": "560077",
        }

    monkeypatch.setattr("app.api.routes.couriers.ShiprocketService.pickup_location_details", pickup_location)
    order = ShopifyOrder(
        order_id="gid-2", order_number="324000", created_date="2026-07-27T00:00:00Z",
        phone="9999999999",
        shipping_address=ShippingAddress(address="12 Main Road", city="Delhi", state="Delhi", pincode="110001"),
        products=[OrderProduct(product_name="Cookies", quantity=1, price=Decimal("250"))],
        total_amount=Decimal("250"), order_total=Decimal("250"), payment_type="prepaid", tags=[],
    )

    with pytest.raises(HTTPException, match="Customer name is required for Shadowfax booking"):
        await _build_provider_booking_request(
            order, {}, PackageDetailsPayload(weight_kg=0.5, length_cm=20, breadth_cm=15, height_cm=10)
        )


@pytest.mark.anyio
async def test_official_shadowfax_http_transport_contract():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Token staging-secret"
        assert request.headers["content-type"] == "application/json"
        if request.url.path.endswith("/serviceability/"):
            return httpx.Response(200, json=[{"code": 560077, "services": ["Regular", "Surface"]}])
        if request.url.path.endswith("/v3/clients/orders/"):
            assert request.method == "POST"
            assert __import__("json").loads(request.content) == official_booking_payload()
            return httpx.Response(200, json={"message": "Success", "errors": None, "data": {"id": 42, "client_order_id": "STAGE-1", "awb_number": "SF-STAGE-1", "status": "new", "customer_track_url": "https://exp.shadowfax.in/test"}})
        if request.url.path.endswith("/track/"):
            return httpx.Response(200, json={"message": "Success", "order_details": {"awb_number": "SF-STAGE-1", "status": "ofd", "customer_track_url": "https://exp.shadowfax.in/test"}, "tracking_details": [{"created": "2026-07-27T10:00:00Z", "location": "BLR Hub", "status_id": "ofd", "remarks": "Item OFD"}]})
        if request.url.path.endswith("/cancel/"):
            assert __import__("json").loads(request.content) == {"request_id": "SF-STAGE-1", "cancel_remarks": "Request cancelled by customer"}
            return httpx.Response(200, json={"responseMsg": "Request has been marked as cancelled", "responseCode": 200})
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = ShadowfaxHTTPTransport(token="staging-secret", base_url="https://shadowfax.example/api", client=client)
        assert await transport.authenticate() is True
        serviceability = await transport.serviceability({"delivery_pincode": "560077"})
        assert serviceability["serviceable"] is True and serviceability["service_type"] == "Regular"
        booking = await transport.create_booking(official_booking_payload())
        assert booking["awb"] == "SF-STAGE-1" and booking["shipment_id"] == "42"
        tracking = await transport.track_shipment({"awb": "SF-STAGE-1"})
        assert tracking["status"] == "ofd" and tracking["latest_scan"] == "BLR Hub"
        cancellation = await transport.cancel_booking({"awb": "SF-STAGE-1"})
        assert cancellation["cancelled"] is True
    assert [request.method for request in requests] == ["GET", "GET", "POST", "GET", "POST"]


def test_shadowfax_http_transport_accepts_configured_https_base_url_and_rejects_http():
    transport = ShadowfaxHTTPTransport(token="secret", base_url="https://shadowfax.example/api")
    assert transport._base_url == "https://shadowfax.example/api"
    with pytest.raises(ProviderConfigurationError, match="valid HTTPS URL"):
        ShadowfaxHTTPTransport(token="secret", base_url="http://shadowfax.example/api")


@pytest.mark.anyio
async def test_shadowfax_http_transport_rejects_application_level_booking_failure():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "Failure", "errors": "Invalid Delivery Pincode"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = ShadowfaxHTTPTransport(token="secret", base_url="https://shadowfax.example/api", client=client)
        with pytest.raises(ProviderError, match="Invalid Delivery Pincode"):
            await transport.create_booking(official_booking_payload())


@pytest.mark.anyio
async def test_shadowfax_label_and_client_order_reconciliation_fail_closed_when_undocumented():
    transport = ShadowfaxHTTPTransport(token="secret", base_url="https://shadowfax.example/api", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))))
    try:
        with pytest.raises(ProviderConfigurationError, match="does not document a shipping-label endpoint"):
            await transport.download_label({"awb": "SF-STAGE-1"})
        with pytest.raises(ProviderConfigurationError, match="does not document lookup by client_order_id"):
            await transport.find_booking("STAGE-1")
    finally:
        await transport._client.aclose()


class MockTransport:
    def __init__(self) -> None: self.booking_calls = 0
    async def authenticate(self): return True
    async def serviceability(self, _request): return {"serviceable": True, "service_id": "surface", "courier_name": "Shadowfax Direct", "charges": 59, "estimated_delivery_days": 2, "service_type": "surface"}
    async def create_booking(self, _request): self.booking_calls += 1; return {"provider_order_id": "SFX-1", "shipment_id": "TASK-1", "awb": "AWB-1", "status": "booked", "tracking_url": "https://tracking.invalid/AWB-1", "service": "Surface", "label_format": "pdf"}
    async def find_booking(self, _merchant_order_id): return None
    async def track_shipment(self, _shipment): return {"status": "out_for_delivery", "latest_scan": "Bengaluru Hub", "timestamp": datetime.now(timezone.utc), "tracking_url": "https://tracking.invalid/AWB-1"}
    async def cancel_booking(self, _shipment): return {"cancelled": True, "status": "cancelled", "message": "Accepted"}
    async def download_label(self, _shipment): return b"%PDF-1.4\n", "application/pdf", None


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(order_operations, "OPS_FILE", tmp_path / "ops.json")
    with Session(engine) as session: yield session


@pytest.mark.anyio
async def test_shadowfax_configuration_fails_closed():
    adapter = ShadowfaxAdapter(token="token", base_url="")
    with pytest.raises(ProviderConfigurationError, match="SHADOWFAX_BASE_URL"):
        await adapter.authenticate()


def test_registry_exposes_provider_capabilities_without_secrets():
    capabilities = courier_registry.capabilities()
    assert set(capabilities) == {"shiprocket", "delhivery", "shadowfax"}
    assert capabilities["shadowfax"]["booking"] is True
    assert "token" not in str(capabilities).casefold()


@pytest.mark.anyio
async def test_shadowfax_mock_auth_serviceability_booking_tracking_cancellation_and_label():
    transport = MockTransport(); adapter = ShadowfaxAdapter(token="secret", base_url="https://official.invalid", transport=transport)
    assert await adapter.authenticate() is True
    serviceability = await adapter.serviceability({"delivery_pincode": "560001"})
    assert serviceability.serviceable and serviceability.quotes[0].charges == 59
    booking = await adapter.create_booking({"merchant_order_id": "1"})
    assert booking.awb == "AWB-1" and booking.status == NormalizedShipmentStatus.BOOKED
    tracking = await adapter.track_shipment({"awb": booking.awb})
    assert tracking.status == NormalizedShipmentStatus.OUT_FOR_DELIVERY
    label = await adapter.download_label({"awb": booking.awb})
    assert label.format == LabelFormat.PDF
    cancellation = await adapter.cancel_booking({"awb": booking.awb, "latest_status": "booked"})
    assert cancellation.cancelled is True


@pytest.mark.anyio
async def test_duplicate_booking_is_prevented(db):
    transport = MockTransport(); adapter = ShadowfaxAdapter(token="secret", base_url="https://official.invalid", transport=transport)
    platform = CourierPlatformService()
    first = await platform.book(db, order_id="1", merchant_order_id="1001", adapter=adapter, request={}, operator="Operator")
    second = await platform.book(db, order_id="1", merchant_order_id="1001", adapter=adapter, request={}, operator="Operator")
    assert first["shipment"]["awb"] == "AWB-1" and second["existing"] is True
    assert transport.booking_calls == 1


@pytest.mark.anyio
async def test_shadowfax_unsupported_client_order_lookup_does_not_block_booking(db):
    class OfficialTransport(MockTransport):
        async def find_booking(self, _merchant_order_id):
            raise ProviderConfigurationError(
                "The official Shadowfax specification does not document lookup by client_order_id. Reconcile using a known AWB.",
                provider="shadowfax",
                operation="reconciliation",
            )

    transport = OfficialTransport()
    adapter = ShadowfaxAdapter(token="secret", base_url="https://official.invalid", transport=transport)

    result = await CourierPlatformService().book(
        db,
        order_id="shadowfax-new",
        merchant_order_id="1004",
        adapter=adapter,
        request={},
        operator="Operator",
    )

    assert result["shipment"]["awb"] == "AWB-1"
    assert transport.booking_calls == 1


@pytest.mark.anyio
async def test_shadowfax_explicit_reconciliation_keeps_unsupported_lookup_warning(db):
    class OfficialTransport(MockTransport):
        async def find_booking(self, _merchant_order_id):
            raise ProviderConfigurationError(
                "The official Shadowfax specification does not document lookup by client_order_id. Reconcile using a known AWB.",
                provider="shadowfax",
                operation="reconciliation",
            )

    adapter = ShadowfaxAdapter(token="secret", base_url="https://official.invalid", transport=OfficialTransport())
    upsert_shipment(
        db,
        "shadowfax-reconcile",
        provider="shadowfax",
        provider_order_id="1005",
        booking_status="booking_uncertain",
        booking_confidence="uncertain",
        reconciliation_status="pending",
    )

    with pytest.raises(ProviderConfigurationError, match="does not document lookup by client_order_id"):
        await CourierPlatformService().reconcile(
            db,
            order_id="shadowfax-reconcile",
            adapter=adapter,
            operator="Operator",
        )


@pytest.mark.anyio
async def test_uncertain_booking_blocks_retry(db):
    class TimeoutTransport(MockTransport):
        async def create_booking(self, _request): self.booking_calls += 1; raise TimeoutError("timeout")
    transport = TimeoutTransport(); adapter = ShadowfaxAdapter(token="secret", base_url="https://official.invalid", transport=transport)
    platform = CourierPlatformService()
    with pytest.raises(TimeoutError): await platform.book(db, order_id="2", merchant_order_id="1002", adapter=adapter, request={}, operator="Operator")
    stored = get_shipment(db, "2")
    assert stored.booking_confidence == BookingConfidence.UNCERTAIN
    assert stored.reconciliation_status == ReconciliationStatus.PENDING
    with pytest.raises(ProviderError, match="uncertain outcome"):
        await platform.book(db, order_id="2", merchant_order_id="1002", adapter=adapter, request={}, operator="Operator")
    assert transport.booking_calls == 1


@pytest.mark.anyio
async def test_booking_reconciliation_recovers_uncertain_state(db):
    class ReconcileTransport(MockTransport):
        async def find_booking(self, _merchant_order_id):
            return {"provider_order_id": "SFX-R", "shipment_id": "TASK-R", "awb": "AWB-R", "status": "booked", "service": "Surface"}
    adapter = ShadowfaxAdapter(token="secret", base_url="https://official.invalid", transport=ReconcileTransport())
    upsert_shipment(db, "reconcile", provider="shadowfax", provider_order_id="1003", booking_status="booking_uncertain", booking_confidence="uncertain", reconciliation_status="pending")
    result = await CourierPlatformService().reconcile(db, order_id="reconcile", adapter=adapter, operator="Operator")
    assert result["awb"] == "AWB-R"
    assert result["booking_confidence"] == "reconciled"
    assert result["reconciliation_status"] == "confirmed"


@pytest.mark.anyio
async def test_cancellation_protects_shipped_orders():
    adapter = ShadowfaxAdapter(token="secret", base_url="https://official.invalid", transport=MockTransport())
    with pytest.raises(ProviderError, match="cannot use normal cancellation"):
        await adapter.cancel_booking({"awb": "A", "normalized_status": "in_transit"})


@pytest.mark.parametrize(("image_format", "label_format"), [("PNG", LabelFormat.PNG), ("JPEG", LabelFormat.JPEG)])
def test_image_label_preserves_exact_four_by_six(image_format, label_format):
    image = Image.new("RGB", (1200, 1800), "white")
    source = BytesIO(); image.save(source, format=image_format, dpi=(300, 300))
    pdf = image_label_to_pdf(source.getvalue(), label_format)
    page = PdfReader(BytesIO(print_ready_pdf(pdf))).pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == (288, 432)


def test_image_label_without_dpi_is_rejected():
    image = Image.new("RGB", (1200, 1800), "white")
    source = BytesIO(); image.save(source, format="PNG")
    with pytest.raises(LabelPrintError, match="no DPI metadata"):
        image_label_to_pdf(source.getvalue(), LabelFormat.PNG)


@pytest.mark.parametrize("dimensions", [(288, 432), (432, 288)])
def test_pdf_four_by_six_preserves_portrait_or_landscape(dimensions):
    page = PdfReader(BytesIO(print_ready_pdf(exact_pdf(*dimensions)))).pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == dimensions


@pytest.mark.anyio
async def test_mixed_provider_batch_and_print_history(db, monkeypatch, tmp_path):
    from app.services import label_printing
    monkeypatch.setattr(label_printing, "LABEL_DIR", tmp_path)
    async def prepared(_self, _shipment): return exact_pdf()
    async def official(_shipment): return exact_pdf()
    monkeypatch.setattr(LabelService, "print_ready", prepared)
    monkeypatch.setattr(label_printing, "official_label", official)
    upsert_shipment(db, "sr", provider="shiprocket", awb="SR1", shipment_id="1", booking_status="booked", label_print_status="not_printed")
    upsert_shipment(db, "dx", provider="delhivery", awb="DX1", shipment_id="2", booking_status="booked", label_print_status="not_printed")
    batch = await create_batch(db, ["sr", "dx"], "Operator")
    assert batch.provider == "mixed"
    assert len(PdfReader(batch.pdf_cache_path).pages) == 2
    confirm_batch(db, batch.id, {"sr", "dx"}, "Operator")
    for order_id in ("sr", "dx"):
        shipment = get_shipment(db, order_id)
        assert shipment.label_print_count == 1
        assert shipment.label_last_printed_by == "Operator"
        assert shipment.label_last_printed_at is not None


def test_webhook_signature_idempotency_and_ndr_persistence(db):
    provider = "mock-courier"
    upsert_shipment(db, "3", provider=provider, provider_order_id="P3", awb="A3", booking_status="booked")
    webhook_registry.register(provider, WebhookHandler(
        lambda _body, headers: headers.get("x-signature") == "valid",
        lambda payload: (str(payload["event_id"]), "3", TrackingResult(provider=provider, status=NormalizedShipmentStatus.NDR, provider_status="NDR", latest_tracking_at=datetime.now(timezone.utc), ndr_reason="Customer unavailable", ndr_attempt=1)),
    ))
    body = b'{"event_id":"evt-1"}'
    first = process_webhook(db, provider=provider, body=body, headers={"x-signature": "valid"}, payload={"event_id": "evt-1"})
    second = process_webhook(db, provider=provider, body=body, headers={"x-signature": "valid"}, payload={"event_id": "evt-1"})
    assert first["duplicate"] is False and second["duplicate"] is True
    assert get_shipment(db, "3").ndr_reason == "Customer unavailable"
