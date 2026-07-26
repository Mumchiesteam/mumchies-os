from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import pytest
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
from app.services.courier_platform.webhooks import WebhookHandler, process_webhook, webhook_registry
from app.services.courier_platform.models import TrackingResult
from app.services.label_printing import LabelPrintError, LabelService, confirm_batch, create_batch, image_label_to_pdf, print_ready_pdf


def exact_pdf(width: int = 288, height: int = 432) -> bytes:
    output = BytesIO(); document = canvas.Canvas(output, pagesize=(width, height))
    document.drawString(20, 20, "provider label"); document.showPage(); document.save()
    return output.getvalue()


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
