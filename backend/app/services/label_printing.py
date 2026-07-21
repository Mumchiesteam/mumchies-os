"""Official-provider label preparation and idempotent print-batch management."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR
from app.models.shiprocket import LabelPrintBatch, LabelPrintBatchItem, ShiprocketShipment
from app.services.delhivery import DelhiveryService
from app.services.shiprocket import ShiprocketService

LABEL_DIR = BACKEND_DIR / "data" / "label_batches"
LABEL_DIR.mkdir(parents=True, exist_ok=True)
TARGETS = ((288.0, 432.0), (432.0, 288.0))


class LabelPrintError(RuntimeError):
    pass


def _dimensions(box) -> tuple[float, float]:
    return float(box.width), float(box.height)


def _is_4x6(box) -> bool:
    width, height = _dimensions(box)
    return any(abs(width - target_width) <= 2 and abs(height - target_height) <= 2 for target_width, target_height in TARGETS)


def print_ready_pdf(source: bytes) -> bytes:
    """Preserve content streams; only use an existing validated 4x6 page box."""
    if not source.startswith(b"%PDF"):
        raise LabelPrintError("The provider response is not a PDF.")
    reader = PdfReader(BytesIO(source))
    writer = PdfWriter()
    for page in reader.pages:
        selected_box = next((box for box in (page.cropbox, page.trimbox, page.artbox, page.mediabox) if _is_4x6(box)), None)
        if selected_box is None:
            width, height = _dimensions(page.mediabox)
            raise LabelPrintError(f"Official label page is {width:.0f} x {height:.0f} points; no provider-defined 4 x 6 page box is available for a safe crop.")
        page.mediabox = selected_box
        page.cropbox = selected_box
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


async def official_label(shipment: ShiprocketShipment) -> bytes:
    if not shipment.awb:
        raise LabelPrintError("Shipment has no AWB.")
    if shipment.provider == "delhivery":
        response = await DelhiveryService().label(shipment.awb)
    elif shipment.provider == "shiprocket" and shipment.shipment_id:
        response = await ShiprocketService().fetch_label(shipment.shipment_id)
    else:
        raise LabelPrintError("This provider does not expose an official PDF label.")
    return response.content


async def create_batch(db: Session, order_ids: list[str], operator: str) -> LabelPrintBatch:
    if not order_ids:
        raise LabelPrintError("Select at least one label.")
    shipments = [db.get(ShiprocketShipment, order_id) for order_id in order_ids]
    if any(shipment is None for shipment in shipments):
        raise LabelPrintError("One or more selected shipments do not exist.")
    providers = {shipment.provider for shipment in shipments if shipment}
    if len(providers) != 1:
        raise LabelPrintError("Create separate print batches for Shiprocket and Delhivery.")
    active = db.scalars(
        select(LabelPrintBatchItem).where(
            LabelPrintBatchItem.order_id.in_(order_ids),
            LabelPrintBatchItem.status == "awaiting_confirmation",
        )
    ).first()
    if active:
        raise LabelPrintError("A selected shipment already belongs to an active print batch.")
    for shipment in shipments:
        if shipment.label_print_status != "not_printed":
            raise LabelPrintError("Only labels currently in the Labels to Print queue can be batched.")

    prepared = [print_ready_pdf(await official_label(shipment)) for shipment in shipments]
    writer = PdfWriter()
    for label in prepared:
        for page in PdfReader(BytesIO(label)).pages:
            writer.add_page(page)
    batch_id = uuid4().hex
    path = LABEL_DIR / f"{batch_id}.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    now = datetime.now(timezone.utc)
    batch = LabelPrintBatch(id=batch_id, provider=str(next(iter(providers))), created_at=now, created_by=operator, status="awaiting_confirmation", pdf_cache_path=str(path))
    db.add(batch)
    for position, shipment in enumerate(shipments):
        shipment.label_print_status = "awaiting_confirmation"
        shipment.last_print_batch_id = batch_id
        db.add(LabelPrintBatchItem(batch_id=batch_id, order_id=shipment.order_id, position=position, status="awaiting_confirmation"))
    db.commit()
    return batch


def confirm_batch(db: Session, batch_id: str, printed_order_ids: set[str], operator: str) -> LabelPrintBatch:
    batch = db.get(LabelPrintBatch, batch_id)
    if batch is None:
        raise LabelPrintError("Print batch not found.")
    if batch.status == "confirmed":
        return batch
    items = db.scalars(select(LabelPrintBatchItem).where(LabelPrintBatchItem.batch_id == batch_id)).all()
    now = datetime.now(timezone.utc)
    for item in items:
        shipment = db.get(ShiprocketShipment, item.order_id)
        if shipment is None:
            continue
        if item.order_id in printed_order_ids:
            if item.status != "printed":
                shipment.label_print_count = int(shipment.label_print_count or 0) + 1
                shipment.label_first_printed_at = shipment.label_first_printed_at or now
                shipment.label_last_printed_at = now
                shipment.label_last_printed_by = operator
            shipment.label_print_status = "printed"
            item.status = "printed"
        else:
            shipment.label_print_status = "not_printed"
            shipment.last_print_batch_id = None
            item.status = "not_printed"
    batch.status = "confirmed"
    batch.confirmed_at = now
    batch.confirmed_by = operator
    db.commit()
    return batch
