from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shiprocket import ShiprocketShipment


def upsert_shipment(db: Session, order_id: str, **fields) -> ShiprocketShipment:
    shipment = db.get(ShiprocketShipment, order_id)
    created = shipment is None
    if shipment is None:
        shipment = ShiprocketShipment(order_id=order_id)
        db.add(shipment)
    for key, value in fields.items():
        setattr(shipment, key, value)
    if created and fields.get("booking_status") == "booked":
        shipment.label_print_status = "not_printed"
        shipment.label_print_count = 0
        shipment.label_tracking_activated_at = datetime.now().astimezone()
    db.commit()
    db.refresh(shipment)
    return shipment


def get_shipment(db: Session, order_id: str) -> ShiprocketShipment | None:
    return db.get(ShiprocketShipment, order_id)


def get_shipments_by_order_id(db: Session) -> dict[str, ShiprocketShipment]:
    """Load shipment state once for the orders-list merge."""
    shipments = db.scalars(select(ShiprocketShipment)).all()
    return {shipment.order_id: shipment for shipment in shipments}


def snapshot(shipment: ShiprocketShipment | None) -> dict[str, object | None]:
    if shipment is None:
        return {
            "order_id": None,
            "provider": None,
            "provider_order_id": None,
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
            "expected_delivery_date": None,
            "delivered_at": None,
            "address_sync_status": None,
            "address_sync_error": None,
            "package_weight_kg": None,
            "package_length_cm": None,
            "package_breadth_cm": None,
            "package_height_cm": None,
            "selected_courier_id": None,
            "selected_courier_name": None,
            "shopify_fulfillment_id": None,
            "shopify_fulfillment_status": None,
            "shopify_fulfillment_sync_status": None,
            "shopify_fulfillment_synced_at": None,
            "shopify_fulfillment_sync_error": None,
            "shopify_tracking_number": None,
            "shopify_tracking_url": None,
            "shopify_customer_notified": None,
            "label_print_status": None,
            "label_first_printed_at": None,
            "label_last_printed_at": None,
            "label_last_printed_by": None,
            "label_print_count": 0,
            "last_print_batch_id": None,
            "label_tracking_activated_at": None,
            "address_confidence_score": None,
            "address_confidence_category": None,
            "address_confidence_source": None,
            "address_confidence_checked_at": None,
        }
    return {
        "order_id": shipment.order_id,
        "provider": shipment.provider,
        "provider_order_id": shipment.provider_order_id,
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
        "expected_delivery_date": shipment.expected_delivery_date,
        "delivered_at": shipment.delivered_at.isoformat() if shipment.delivered_at else None,
        "address_sync_status": shipment.address_sync_status,
        "address_sync_error": shipment.address_sync_error,
        "package_weight_kg": shipment.package_weight_kg,
        "package_length_cm": shipment.package_length_cm,
        "package_breadth_cm": shipment.package_breadth_cm,
        "package_height_cm": shipment.package_height_cm,
        "selected_courier_id": shipment.selected_courier_id,
        "selected_courier_name": shipment.selected_courier_name,
        "shopify_fulfillment_id": shipment.shopify_fulfillment_id,
        "shopify_fulfillment_status": shipment.shopify_fulfillment_status,
        "shopify_fulfillment_sync_status": shipment.shopify_fulfillment_sync_status,
        "shopify_fulfillment_synced_at": shipment.shopify_fulfillment_synced_at.isoformat() if shipment.shopify_fulfillment_synced_at else None,
        "shopify_fulfillment_sync_error": shipment.shopify_fulfillment_sync_error,
        "shopify_tracking_number": shipment.shopify_tracking_number,
        "shopify_tracking_url": shipment.shopify_tracking_url,
        "shopify_customer_notified": shipment.shopify_customer_notified,
        "label_print_status": shipment.label_print_status,
        "label_first_printed_at": shipment.label_first_printed_at.isoformat() if shipment.label_first_printed_at else None,
        "label_last_printed_at": shipment.label_last_printed_at.isoformat() if shipment.label_last_printed_at else None,
        "label_last_printed_by": shipment.label_last_printed_by,
        "label_print_count": shipment.label_print_count,
        "last_print_batch_id": shipment.last_print_batch_id,
        "label_tracking_activated_at": shipment.label_tracking_activated_at.isoformat() if shipment.label_tracking_activated_at else None,
        "address_confidence_score": shipment.address_confidence_score,
        "address_confidence_category": shipment.address_confidence_category,
        "address_confidence_source": shipment.address_confidence_source,
        "address_confidence_checked_at": shipment.address_confidence_checked_at.isoformat() if shipment.address_confidence_checked_at else None,
    }
