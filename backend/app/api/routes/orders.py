from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.orders import ShopifyOrder
from app.repositories.shiprocket import get_shipment
from app.services.order_operations import OrderOperationsStore
from app.services.shiprocket import ShiprocketAPIError, ShiprocketConfigurationError, ShiprocketService
from app.services.shopify import ShopifyConfigurationError, ShopifyService

router = APIRouter(prefix="/orders", tags=["orders"])


class AddressPayload(BaseModel):
    customer_name: str | None = None
    phone: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    landmark: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    courier_sync_status: str | None = None
    courier_sync_error: str | None = None
    verified_by: str | None = None


class CallLogPayload(BaseModel):
    result: str = Field(...)
    timestamp: str | None = None
    operator: str = Field(...)
    comment: str | None = None


class VerifyAddressPayload(BaseModel):
    operator: str = Field(...)
    verified_at: str | None = None
    address_snapshot: dict[str, str | None] = Field(default_factory=dict)


def _merged_operational_state(order: ShopifyOrder, operations: dict[str, object]) -> ShopifyOrder:
    call_logs = operations.get("call_logs") or []
    latest_call = call_logs[0]["result"] if call_logs else None
    shopify_status = (order.shopify_status or "").lower()
    fulfillment_status = (order.fulfillment_status or "").lower()
    tags = " ".join(order.tags).lower()

    operational_status: str | None
    if shopify_status == "cancelled" or fulfillment_status == "cancelled" or order.cancelled_at:
        operational_status = "Cancelled"
    elif "delivered" in tags or fulfillment_status == "delivered":
        operational_status = "Delivered"
    elif "fulfilled" in fulfillment_status or "partial" in fulfillment_status or "shipped" in tags or "dispatched" in tags or "picked up" in tags:
        operational_status = "Shipped"
    elif "ndr" in tags:
        operational_status = "NDR"
    elif latest_call == "Wrong Number":
        operational_status = "Needs Review"
    elif order.payment_status and order.payment_status.lower() not in {"pending", "cod", "partially paid"}:
        operational_status = "Ready for Booking" if operations.get("address_verified") else "Address Verification Pending"
    elif latest_call == "Confirmed":
        operational_status = "Ready for Booking"
    elif latest_call == "Callback Requested":
        operational_status = "Callback Required"
    elif latest_call in {"No Answer", "Busy", "Switched Off"} or latest_call is None:
        operational_status = "Call Pending"
    else:
        operational_status = "Call Pending"

    return order.model_copy(update={
        "latest_call_result": latest_call,
        "operational_status": operational_status,
        "address_verified": bool(operations.get("address_verified")),
        "address_verified_at": operations.get("address_verified_at"),
        "address_verified_by": operations.get("address_verified_by"),
        "verified_address_snapshot": operations.get("verified_address_snapshot"),
        "corrected_address": operations.get("corrected_address"),
        "courier_sync_status": operations.get("courier_sync_status"),
        "courier_sync_error": operations.get("courier_sync_error"),
    })


@router.get("", response_model=list[ShopifyOrder])
async def list_orders() -> list[ShopifyOrder]:
    """Return the latest Shopify orders through a read-only integration."""
    try:
        orders = await ShopifyService().get_latest_orders()
        operations_map = OrderOperationsStore.all()
        return [_merged_operational_state(order, operations_map.get(order.order_id, {})) for order in orders]
    except ShopifyConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except httpx.HTTPStatusError as error:
        raise HTTPException(status_code=502, detail="Shopify could not provide orders. Check the store, token, and API version.") from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Unable to reach Shopify.") from error


@router.get("/{order_id}/operations")
async def get_order_operations(order_id: str) -> dict[str, object]:
    return OrderOperationsStore.get(order_id)


@router.get("/{order_id}/shipping-label")
async def get_shipping_label(order_id: str, db: Session = Depends(get_db)):
    try:
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.awb:
            raise HTTPException(status_code=404, detail="No Shiprocket shipment exists for this order.")
        response = await ShiprocketService().fetch_label(shipment.awb)
        return StreamingResponse(iter([response.content]), media_type=response.headers.get("content-type", "application/pdf"))
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.put("/{order_id}/address")
async def update_order_address(order_id: str, payload: AddressPayload) -> dict[str, object]:
    address = {
        "customer_name": payload.customer_name,
        "phone": payload.phone,
        "address_line1": payload.address_line1,
        "address_line2": payload.address_line2,
        "landmark": payload.landmark,
        "city": payload.city,
        "state": payload.state,
        "pincode": payload.pincode,
    }
    return OrderOperationsStore.save_address(
        order_id,
        address,
        courier_sync_status=payload.courier_sync_status,
        courier_sync_error=payload.courier_sync_error,
    )


@router.post("/{order_id}/call-logs")
async def add_call_log(order_id: str, payload: CallLogPayload) -> dict[str, object]:
    entry = {
        "result": payload.result,
        "timestamp": payload.timestamp or datetime.now().isoformat(timespec="seconds"),
        "operator": payload.operator,
        "comment": payload.comment,
    }
    return OrderOperationsStore.append_call_log(order_id, entry)


@router.post("/{order_id}/address/verify")
async def verify_order_address(order_id: str, payload: VerifyAddressPayload) -> dict[str, object]:
    return OrderOperationsStore.verify_address(
        order_id,
        operator=payload.operator,
        snapshot=payload.address_snapshot,
        verified_at=payload.verified_at or datetime.now().isoformat(timespec="seconds"),
    )
