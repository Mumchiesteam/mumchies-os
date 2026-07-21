from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.shiprocket import LabelPrintBatch, LabelPrintBatchItem, ShiprocketShipment
from app.repositories.shiprocket import snapshot
from app.services.label_printing import LabelPrintError, confirm_batch, create_batch

router = APIRouter(prefix="/labels", tags=["labels"])


class BatchPayload(BaseModel):
    order_ids: list[str]
    operator: str


class ConfirmPayload(BaseModel):
    printed_order_ids: list[str]
    operator: str


class ReprintPayload(BaseModel):
    confirmed: bool


@router.get("/queue")
async def label_queue(db: Session = Depends(get_db)) -> dict[str, object]:
    shipments = db.scalars(select(ShiprocketShipment).where(ShiprocketShipment.label_print_status.in_(["not_printed", "awaiting_confirmation", "printed"]))).all()
    return {
        "labels_to_print": [snapshot(value) for value in shipments if value.label_print_status == "not_printed" and value.booking_status == "booked" and value.awb],
        "awaiting_confirmation": [snapshot(value) for value in shipments if value.label_print_status == "awaiting_confirmation"],
        "printed_today": [snapshot(value) for value in shipments if value.label_print_status == "printed" and value.label_last_printed_at],
    }


@router.get("/batches/active")
async def active_batches(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    batches = db.scalars(select(LabelPrintBatch).where(LabelPrintBatch.status == "awaiting_confirmation")).all()
    result = []
    for batch in batches:
        items = db.scalars(select(LabelPrintBatchItem).where(LabelPrintBatchItem.batch_id == batch.id).order_by(LabelPrintBatchItem.position)).all()
        result.append({"id": batch.id, "provider": batch.provider, "status": batch.status, "order_ids": [item.order_id for item in items]})
    return result


@router.post("/batches")
async def make_batch(payload: BatchPayload, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        batch = await create_batch(db, payload.order_ids, payload.operator)
        return {"id": batch.id, "provider": batch.provider, "status": batch.status, "order_ids": payload.order_ids}
    except LabelPrintError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/batches/{batch_id}/pdf")
async def batch_pdf(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(LabelPrintBatch, batch_id)
    if batch is None or not batch.pdf_cache_path or not Path(batch.pdf_cache_path).is_file():
        raise HTTPException(status_code=404, detail="Print batch PDF is unavailable.")
    return FileResponse(batch.pdf_cache_path, media_type="application/pdf", filename=f"mumchies-labels-{batch_id}.pdf")


@router.post("/batches/{batch_id}/confirm")
async def confirm(batch_id: str, payload: ConfirmPayload, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        batch = confirm_batch(db, batch_id, set(payload.printed_order_ids), payload.operator)
        items = db.scalars(select(LabelPrintBatchItem).where(LabelPrintBatchItem.batch_id == batch_id)).all()
        return {"id": batch.id, "status": batch.status, "items": [{"order_id": value.order_id, "status": value.status} for value in items]}
    except LabelPrintError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/orders/{order_id}/activate")
async def activate_legacy_label(order_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    shipment = db.get(ShiprocketShipment, order_id)
    if shipment is None or not shipment.awb or shipment.booking_status != "booked":
        raise HTTPException(status_code=409, detail="Only an existing booked shipment can be added to the label queue.")
    if shipment.label_print_status is None:
        from datetime import datetime, timezone
        shipment.label_print_status = "not_printed"
        shipment.label_print_count = 0
        shipment.label_tracking_activated_at = datetime.now(timezone.utc)
        db.commit()
    return snapshot(shipment)


@router.post("/orders/{order_id}/reprint")
async def reprint_label(order_id: str, payload: ReprintPayload, db: Session = Depends(get_db)) -> dict[str, object]:
    shipment = db.get(ShiprocketShipment, order_id)
    if shipment is None or shipment.label_print_status != "printed":
        raise HTTPException(status_code=409, detail="Only a previously printed label can be reprinted.")
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Explicit reprint confirmation is required.")
    shipment.label_print_status = "not_printed"
    shipment.last_print_batch_id = None
    db.commit()
    return snapshot(shipment)
