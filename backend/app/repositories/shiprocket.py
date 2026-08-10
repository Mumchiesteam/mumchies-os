from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shiprocket import ShiprocketShipment

ENGAGE_FIELDS = (
    "engage_order_id", "order_confirmation", "order_confirmation_message",
    "address_confirmation", "address_confirmation_message", "cod_to_prepaid",
    "cod_to_prepaid_message", "engage_last_synced_at", "engage_raw_status",
)


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


def get_shipments_by_order_id(db: Session, order_ids: list[str] | None = None) -> dict[str, ShiprocketShipment]:
    """Load shipment state once for the orders-list merge."""
    query = select(ShiprocketShipment)
    if order_ids is not None:
        if not order_ids:
            return {}
        query = query.where(ShiprocketShipment.order_id.in_(order_ids))
    shipments = db.scalars(query).all()
    return {shipment.order_id: shipment for shipment in shipments}


def _channel_order_key(value: object) -> str:
    return str(value).strip() if value is not None else ""


def sync_engage_orders(db: Session, orders_by_number: dict[str, str], upstream_orders: list[dict], synced_at: datetime) -> None:
    """Bulk-persist Engage fields already present in a Shiprocket Orders response."""
    upstream_by_number = {_channel_order_key(row.get("channel_order_id")): row for row in upstream_orders if isinstance(row, dict)}
    existing = get_shipments_by_order_id(db)
    for number, order_id in orders_by_number.items():
        normalized_number = _channel_order_key(number)
        upstream = upstream_by_number.get(normalized_number)
        if upstream is None:
            continue
        shipment = existing.get(order_id)
        if shipment is None:
            shipment = ShiprocketShipment(order_id=order_id)
            db.add(shipment)
        engage = upstream.get("engage")
        engage = engage if isinstance(engage, dict) else None
        shipment.shiprocket_order_id = str(upstream.get("id")) if upstream.get("id") is not None else shipment.shiprocket_order_id
        # The channel order number is a Shiprocket reference only. Never overwrite
        # another provider's canonical identifier while syncing Engage metadata.
        if str(shipment.provider or "").casefold() in {"", "shiprocket"}:
            shipment.provider_order_id = normalized_number
        shipment.engage_order_id = str(engage.get("engage_order_id")) if engage and engage.get("engage_order_id") is not None else None
        for field in ("order_confirmation", "order_confirmation_message", "address_confirmation", "address_confirmation_message", "cod_to_prepaid", "cod_to_prepaid_message"):
            setattr(shipment, field, engage.get(field) if engage else None)
        shipment.engage_raw_status = engage
        shipment.engage_last_synced_at = synced_at
    db.commit()


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
            "booking_mode": None, "booking_freight": None, "booking_operator": None, "booking_note": None,
            "booked_at": None,
            "latest_status": None,
            "normalized_status": None,
            "courier_service": None,
            "latest_tracking_at": None,
            "latest_scan": None,
            "terminal_status": None,
            "last_synced_at": None,
            "tracking_url": None,
            "label_url": None,
            "label_format": None,
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
            "raw_provider_response": None,
            "booking_confidence": None,
            "reconciliation_status": None,
            "reconciliation_error": None,
            "ndr_reason": None,
            "ndr_attempt": None,
            "ndr_remarks": None,
            "ndr_operator_action": None,
            "address_confidence_score": None,
            "address_confidence_category": None,
            "address_confidence_source": None,
            "address_confidence_checked_at": None,
            "engage_order_id": None,
            "order_confirmation": None,
            "order_confirmation_message": None,
            "address_confirmation": None,
            "address_confirmation_message": None,
            "cod_to_prepaid": None,
            "cod_to_prepaid_message": None,
            "engage_last_synced_at": None,
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
        "booking_mode": shipment.booking_mode,
        "booking_freight": shipment.booking_freight,
        "booking_operator": shipment.booking_operator,
        "booking_note": shipment.booking_note,
        "booked_at": shipment.booked_at.isoformat() if shipment.booked_at else None,
        "latest_status": shipment.latest_status,
        "normalized_status": shipment.normalized_status,
        "courier_service": shipment.courier_service,
        "latest_tracking_at": shipment.latest_tracking_at.isoformat() if shipment.latest_tracking_at else None,
        "latest_scan": shipment.latest_scan,
        "terminal_status": shipment.terminal_status,
        "last_synced_at": shipment.last_synced_at.isoformat() if shipment.last_synced_at else None,
        "tracking_url": shipment.tracking_url,
        "label_url": shipment.label_url,
        "label_format": shipment.label_format,
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
        "raw_provider_response": shipment.raw_provider_response,
        "booking_confidence": shipment.booking_confidence,
        "reconciliation_status": shipment.reconciliation_status,
        "reconciliation_error": shipment.reconciliation_error,
        "ndr_reason": shipment.ndr_reason,
        "ndr_attempt": shipment.ndr_attempt,
        "ndr_remarks": shipment.ndr_remarks,
        "ndr_operator_action": shipment.ndr_operator_action,
        "address_confidence_score": shipment.address_confidence_score,
        "address_confidence_category": shipment.address_confidence_category,
        "address_confidence_source": shipment.address_confidence_source,
        "address_confidence_checked_at": shipment.address_confidence_checked_at.isoformat() if shipment.address_confidence_checked_at else None,
        "engage_order_id": shipment.engage_order_id,
        "order_confirmation": shipment.order_confirmation,
        "order_confirmation_message": shipment.order_confirmation_message,
        "address_confirmation": shipment.address_confirmation,
        "address_confirmation_message": shipment.address_confirmation_message,
        "cod_to_prepaid": shipment.cod_to_prepaid,
        "cod_to_prepaid_message": shipment.cod_to_prepaid_message,
        "engage_last_synced_at": shipment.engage_last_synced_at.isoformat() if shipment.engage_last_synced_at else None,
    }
