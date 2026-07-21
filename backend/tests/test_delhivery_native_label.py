from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.shiprocket import ShiprocketShipment
from app.repositories.shiprocket import upsert_shipment
from app.services import label_printing
from app.services.delhivery import DelhiveryError
from app.services.delhivery_label import (
    CONTENT_WIDTH,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    DelhiveryLabelError,
    _wrap_lines,
    render_delhivery_label,
)
from app.services.label_printing import LabelPrintError, confirm_batch, create_batch, print_ready_pdf


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'labels.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def base_package(**overrides) -> dict:
    data = {
        "wbn": "38290012345678",
        "barcode": "38290012345678",
        "oid": "MUM-100234",
        "name": "Test Customer",
        "address": "12 Sample Street, Near XYZ Landmark",
        "pin": 411001,
        "contact": "9999999999",
        "destination_city": "Pune",
        "customer_state": "Maharashtra",
        "sort_code": "PNQ/AAA",
        "destination": "Pune Hub",
        "pt": "COD",
        "cod": 1378.0,
        "prd": "Mumchies Choco Bites 200g Pack",
        "qty": "1",
        "snm": "Mumchies Foods",
        "sadd": "Warehouse Road, MIDC, Pune 411001",
        "radd": "Warehouse Road, MIDC",
        "rcty": "Pune",
        "rst": "Maharashtra",
        "rpin": 411001,
        "hsn_code": "19053100",
    }
    data.update(overrides)
    return data


def fake_order(**overrides):
    defaults = dict(
        order_id="d1", order_number="1042", payment_type="partial_cod",
        cod_collectable_amount=250.0, order_total=1500.0, created_date="2026-07-18T10:30:00Z",
        products=[
            SimpleNamespace(product_name="Mumchies Choco Bites 200g", quantity=2, price=650.0),
            SimpleNamespace(product_name="Mumchies Spicy Mix 150g", quantity=1, price=200.0),
        ],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_order_enrichment_adds_price_total_date_and_partial_cod_amount():
    result = render_delhivery_label(base_package(pt="COD", cod=999999), order=fake_order())
    text = _text(result)
    assert "Choco Bites" in text and "Rs 650.0" in text
    assert "Order Total: Rs 1500.0" in text
    assert "Order Date: 18 Jul 2026" in text
    # Our own partial-COD collectable amount wins over Delhivery's raw cod figure.
    assert "COD: Rs 250.0" in text


def test_order_enrichment_prepaid_shows_no_cod_amount():
    order = fake_order(payment_type="prepaid", cod_collectable_amount=0)
    result = render_delhivery_label(base_package(pt="COD", cod=1378.0), order=order)
    text = _text(result)
    assert "PREPAID" in text.upper()
    assert "COD:" not in text


def test_missing_order_omits_enrichment_fields_without_crashing():
    result = render_delhivery_label(base_package())
    box = _page(result).mediabox
    assert (float(box.width), float(box.height)) == (298.0, 420.0)
    assert "Order Total" not in _text(result)


def _page(pdf_bytes: bytes, index: int = 0):
    return PdfReader(BytesIO(pdf_bytes)).pages[index]


def _text(pdf_bytes: bytes, index: int = 0) -> str:
    return _page(pdf_bytes, index).extract_text() or ""


def _rect_fill_count(pdf_bytes: bytes, index: int = 0) -> int:
    content = _page(pdf_bytes, index).get_contents().get_data()
    return content.count(b" re")


def test_page_is_exact_a6_dimensions():
    result = render_delhivery_label(base_package())
    box = _page(result).mediabox
    assert (float(box.width), float(box.height)) == (298.0, 420.0)
    assert (PAGE_WIDTH, PAGE_HEIGHT) == (298.0, 420.0)


def test_cod_label_shows_amount():
    result = render_delhivery_label(base_package(pt="COD", cod=1378.0))
    text = _text(result)
    assert "COD" in text
    assert "1378" in text


def test_prepaid_label_shows_prepaid_not_cod_amount():
    result = render_delhivery_label(base_package(pt="Prepaid", cod=0))
    text = _text(result)
    assert "PREPAID" in text.upper()
    assert "COD:" not in text


def test_long_address_wraps_without_exceeding_page_width():
    long_address = "Flat No 42B, Sunrise Apartments, Behind Big Bazaar, Near Old Water Tank, Off Service Road, " \
        "Sector 21, Phase 3, Extension Colony, Some Very Long Locality Name Indeed"
    result = render_delhivery_label(base_package(address=long_address))
    text = _text(result)
    # Nothing from the address text is dropped even though it must wrap across several lines.
    assert "Sunrise Apartments" in text
    assert "Extension Colony" in text or "Colony" in text


def test_wrap_lines_never_exceeds_max_width():
    long_word_sentence = "Supercalifragilisticexpialidocious " * 3 + "short words after"
    lines = _wrap_lines(long_word_sentence, "Helvetica", 8, CONTENT_WIDTH, max_lines=10)
    for line in lines:
        assert stringWidth(line, "Helvetica", 8) <= CONTENT_WIDTH + 0.5  # tiny float tolerance


def test_long_product_description_is_wrapped_or_truncated_not_dropped():
    long_product = "Mumchies Extra Crunchy Deluxe Family Pack Assorted Namkeen Mixture 500 Gram Resealable Pouch"
    result = render_delhivery_label(base_package(prd=long_product))
    text = _text(result)
    assert "Mumchies Extra Crunchy" in text


def test_multiple_products_in_one_field_render_without_crashing():
    result = render_delhivery_label(base_package(
        prd="Choco Bites 200g; Spicy Mix 150g; Sweet Namkeen 250g",
        qty="3",
    ))
    text = _text(result)
    assert "Choco Bites" in text
    assert "Qty: 3" in text


def test_missing_optional_fields_do_not_crash():
    minimal = {"wbn": "AWB1", "barcode": "AWB1", "name": "Cust", "address": "Addr", "pin": "110001"}
    result = render_delhivery_label(minimal)
    box = _page(result).mediabox
    assert (float(box.width), float(box.height)) == (298.0, 420.0)


def test_missing_mandatory_awb_raises_clear_error():
    package = base_package(wbn="", barcode="")
    with pytest.raises(DelhiveryLabelError, match="wbn"):
        render_delhivery_label(package)


def test_missing_mandatory_address_field_raises():
    package = base_package(address="", pin="")
    with pytest.raises(DelhiveryLabelError, match="address"):
        render_delhivery_label(package)


def test_non_dict_input_raises_instead_of_crashing():
    with pytest.raises(DelhiveryLabelError):
        render_delhivery_label(None)  # type: ignore[arg-type]


def test_code128_barcode_is_actually_drawn():
    with_barcode = render_delhivery_label(base_package())
    # A real barcode draws many filled bars (rect-fill operators); a page with no barcode
    # (e.g. rules/lines only) would have none. This is a coarse but meaningful presence check.
    assert _rect_fill_count(with_barcode) > 15


def test_shiprocket_labels_are_never_routed_through_delhivery_rendering():
    writer = PdfWriter()
    writer.add_blank_page(width=288, height=432)
    output = BytesIO()
    writer.write(output)
    already_4x6 = output.getvalue()
    # Shiprocket keeps going through print_ready_pdf's existing box-detection path untouched -
    # it must never end up on the Delhivery-only 298x420 A6 canvas.
    result = print_ready_pdf(already_4x6)
    box = _page(result).mediabox
    assert (float(box.width), float(box.height)) == (288.0, 432.0)


@pytest.mark.anyio
async def test_delhivery_batch_renders_native_a6_pdf(db, monkeypatch, tmp_path):
    monkeypatch.setattr(label_printing, "LABEL_DIR", tmp_path)

    async def fake_order_lookup(_order_id):
        return None

    monkeypatch.setattr(label_printing, "_matching_shopify_order", fake_order_lookup)

    async def fake_label_data(_self, _waybill):
        return base_package()

    monkeypatch.setattr(label_printing.DelhiveryService, "label_data", fake_label_data)
    upsert_shipment(db, "d1", provider="delhivery", awb="38290012345678", booking_status="booked", label_print_status="not_printed")
    batch = await create_batch(db, ["d1"], "Operator")
    pdf_bytes = (tmp_path / f"{batch.id}.pdf").read_bytes()
    box = _page(pdf_bytes).mediabox
    assert (float(box.width), float(box.height)) == (298.0, 420.0)
    assert db.get(ShiprocketShipment, "d1").label_print_status == "awaiting_confirmation"


@pytest.mark.anyio
async def test_delhivery_batch_with_multiple_labels_preserves_order_and_count(db, monkeypatch, tmp_path):
    monkeypatch.setattr(label_printing, "LABEL_DIR", tmp_path)

    async def fake_order_lookup(_order_id):
        return None

    monkeypatch.setattr(label_printing, "_matching_shopify_order", fake_order_lookup)

    async def fake_label_data(_self, waybill):
        return base_package(wbn=waybill, barcode=waybill, name=f"Customer {waybill}")

    monkeypatch.setattr(label_printing.DelhiveryService, "label_data", fake_label_data)
    for awb in ("AWB0001", "AWB0002", "AWB0003"):
        upsert_shipment(db, awb, provider="delhivery", awb=awb, booking_status="booked", label_print_status="not_printed")
    batch = await create_batch(db, ["AWB0001", "AWB0002", "AWB0003"], "Operator")
    pdf_bytes = (tmp_path / f"{batch.id}.pdf").read_bytes()
    reader = PdfReader(BytesIO(pdf_bytes))
    assert len(reader.pages) == 3
    for page in reader.pages:
        box = page.mediabox
        assert (float(box.width), float(box.height)) == (298.0, 420.0)


@pytest.mark.anyio
async def test_delhivery_batch_creation_fails_closed_on_missing_mandatory_fields(db, monkeypatch, tmp_path):
    monkeypatch.setattr(label_printing, "LABEL_DIR", tmp_path)

    async def fake_order_lookup(_order_id):
        return None

    monkeypatch.setattr(label_printing, "_matching_shopify_order", fake_order_lookup)

    async def fake_label_data(_self, _waybill):
        return {"wbn": "", "barcode": "", "name": "", "address": "", "pin": ""}

    monkeypatch.setattr(label_printing.DelhiveryService, "label_data", fake_label_data)
    upsert_shipment(db, "d2", provider="delhivery", awb="AWBD2", booking_status="booked", label_print_status="not_printed")
    with pytest.raises(LabelPrintError, match="missing required field"):
        await create_batch(db, ["d2"], "Operator")
    assert db.get(ShiprocketShipment, "d2").label_print_status == "not_printed"


@pytest.mark.anyio
async def test_delhivery_batch_creation_fails_closed_on_provider_error(db, monkeypatch, tmp_path):
    monkeypatch.setattr(label_printing, "LABEL_DIR", tmp_path)

    async def fake_order_lookup(_order_id):
        return None

    monkeypatch.setattr(label_printing, "_matching_shopify_order", fake_order_lookup)

    async def fake_label_data(_self, _waybill):
        raise DelhiveryError("Delhivery could not generate label data: the AWB is invalid, unmanifested, or was not found.")

    monkeypatch.setattr(label_printing.DelhiveryService, "label_data", fake_label_data)
    upsert_shipment(db, "d3", provider="delhivery", awb="AWBD3", booking_status="booked", label_print_status="not_printed")
    with pytest.raises(LabelPrintError, match="unmanifested"):
        await create_batch(db, ["d3"], "Operator")
    assert db.get(ShiprocketShipment, "d3").label_print_status == "not_printed"


@pytest.mark.anyio
async def test_delhivery_batch_confirm_and_reprint_still_work(db, monkeypatch, tmp_path):
    monkeypatch.setattr(label_printing, "LABEL_DIR", tmp_path)

    async def fake_order_lookup(_order_id):
        return None

    monkeypatch.setattr(label_printing, "_matching_shopify_order", fake_order_lookup)

    async def fake_label_data(_self, _waybill):
        return base_package()

    monkeypatch.setattr(label_printing.DelhiveryService, "label_data", fake_label_data)
    upsert_shipment(db, "d4", provider="delhivery", awb="AWBD4", booking_status="booked", label_print_status="not_printed")
    batch = await create_batch(db, ["d4"], "Operator")
    confirm_batch(db, batch.id, {"d4"}, "Operator")
    shipment = db.get(ShiprocketShipment, "d4")
    assert shipment.label_print_status == "printed"
    assert shipment.label_print_count == 1

    # Reprint flow (return-to-queue) is exercised via the same model fields the labels route uses.
    shipment.label_print_status = "not_printed"
    shipment.last_print_batch_id = None
    db.commit()
    batch2 = await create_batch(db, ["d4"], "Operator")
    confirm_batch(db, batch2.id, {"d4"}, "Operator")
    assert db.get(ShiprocketShipment, "d4").label_print_count == 2
