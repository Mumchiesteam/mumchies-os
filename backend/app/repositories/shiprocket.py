from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.shiprocket import ShiprocketShipment


def upsert_shipment(db: Session, order_id: str, **fields) -> ShiprocketShipment:
    shipment = db.get(ShiprocketShipment, order_id)
    if shipment is None:
        shipment = ShiprocketShipment(order_id=order_id)
        db.add(shipment)
    for key, value in fields.items():
        setattr(shipment, key, value)
    db.commit()
    db.refresh(shipment)
    return shipment


def get_shipment(db: Session, order_id: str) -> ShiprocketShipment | None:
    return db.get(ShiprocketShipment, order_id)


def snapshot(shipment: ShiprocketShipment | None) -> dict[str, object | None]:
    if shipment is None:
        return {
            "shiprocket_order_id": None,
            "shipment_id": None,
            "awb": None,
            "courier_name": None,
            "courier_id": None,
            "booking_status": None,
            "booked_at": None,
            "latest_status": None,
            "last_synced_at": None,
            "tracking_url": None,
            "label_url": None,
            "address_sync_status": None,
            "address_sync_error": None,
        }
    return {
        "shiprocket_order_id": shipment.shiprocket_order_id,
        "shipment_id": shipment.shipment_id,
        "awb": shipment.awb,
        "courier_name": shipment.courier_name,
        "courier_id": shipment.courier_id,
        "booking_status": shipment.booking_status,
        "booked_at": shipment.booked_at.isoformat() if shipment.booked_at else None,
        "latest_status": shipment.latest_status,
        "last_synced_at": shipment.last_synced_at.isoformat() if shipment.last_synced_at else None,
        "tracking_url": shipment.tracking_url,
        "label_url": shipment.label_url,
        "address_sync_status": shipment.address_sync_status,
        "address_sync_error": shipment.address_sync_error,
    }
