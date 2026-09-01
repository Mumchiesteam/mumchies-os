import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.routes.couriers import (
    PackageDetailsPayload,
    _build_provider_booking_request,
    _cached_shiprocket_pickup_location_details,
    _load_context,
    _validate_shadowfax_booking_request,
)
from app.db.session import get_db
from app.services.courier_platform.adapters import ShadowfaxAdapter
from app.services.courier_platform.base import ProviderError
from app.services.shipment_status import has_existing_shipment_evidence
from app.services.shadowfax_diagnostics import shadowfax_health_check

router = APIRouter(prefix="/shadowfax", tags=["shadowfax"])
_create_only_attempted_order_ids: set[str] = set()
_create_only_attempt_lock = asyncio.Lock()


@router.get("/health-check")
async def shadowfax_read_only_health_check(request: Request) -> dict[str, object]:
    user = getattr(request.state, "auth_user", None)
    if user is None or user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return await shadowfax_health_check()


def _require_shadowfax_admin(request: Request) -> None:
    user = getattr(request.state, "auth_user", None)
    if user is None or user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")


def _create_payload_summary(payload: dict[str, Any]) -> dict[str, object]:
    order = payload.get("order_details") if isinstance(payload.get("order_details"), dict) else {}
    customer = payload.get("customer_details") if isinstance(payload.get("customer_details"), dict) else {}
    pickup = payload.get("pickup_details") if isinstance(payload.get("pickup_details"), dict) else {}
    return {
        "order_type": payload.get("order_type"),
        "client_order_id": order.get("client_order_id"),
        "client_name": order.get("client_name"),
        "payment_mode": order.get("payment_mode"),
        "cod_amount": order.get("cod_amount"),
        "total_amount": order.get("total_amount"),
        "actual_weight_g": order.get("actual_weight"),
        "volumetric_weight_g": order.get("volumetric_weight"),
        "customer_pincode": customer.get("pincode"),
        "pickup_pincode": pickup.get("pincode"),
        "rto_pincode": (payload.get("rto_details") or {}).get("pincode") if isinstance(payload.get("rto_details"), dict) else None,
        "product_count": len(payload.get("product_details") or []),
    }


@router.post("/test-create-order/{order_id}")
async def shadowfax_create_only_diagnostic(
    order_id: str, request: Request, db: Session = Depends(get_db),
) -> dict[str, object]:
    """One explicit Shadowfax POST with no persistence or secondary provider actions."""
    _require_shadowfax_admin(request)
    order, operations, shipment = await _load_context(order_id, db)
    if order.cancelled_at or str(order.shopify_status or "").casefold() in {"cancelled", "canceled"}:
        raise HTTPException(status_code=409, detail="Cancelled orders cannot be used for the Shadowfax create-only diagnostic.")
    if str(order.fulfillment_status or "unfulfilled").casefold() != "unfulfilled":
        raise HTTPException(status_code=409, detail="Fulfilled orders cannot be used for the Shadowfax create-only diagnostic.")
    if has_existing_shipment_evidence(order, operations, shipment):
        raise HTTPException(status_code=409, detail="Orders with existing shipment evidence cannot be used for the Shadowfax create-only diagnostic.")
    package_data = operations.get("package_details")
    if not isinstance(package_data, dict):
        raise HTTPException(status_code=409, detail="Package details are required before the Shadowfax create-only diagnostic.")
    warehouse = _cached_shiprocket_pickup_location_details()
    if warehouse is None:
        raise HTTPException(
            status_code=409,
            detail="A cached Mumchies pickup snapshot is required. Reload courier options, then retry; this diagnostic will not call Shiprocket.",
        )

    package = PackageDetailsPayload.model_validate(package_data)
    payload = await _build_provider_booking_request(order, operations, package, warehouse=warehouse)
    _validate_shadowfax_booking_request(payload)
    summary = _create_payload_summary(payload)

    # This route intentionally invokes exactly one method: Shadowfax create_booking.
    # It never persists a shipment, starts tracking, synchronizes Shopify, or cleans up providers.
    async with _create_only_attempt_lock:
        if order_id in _create_only_attempted_order_ids:
            raise HTTPException(status_code=409, detail="The create-only diagnostic was already attempted for this order in this backend process.")
        _create_only_attempted_order_ids.add(order_id)
    try:
        booking = await ShadowfaxAdapter().create_booking(payload)
    except ProviderError as error:
        return {
            "outcome": "provider_rejected" if not error.uncertain else "provider_outcome_unknown",
            "http_status": error.http_status,
            "message": str(error),
            "validation_errors": [str(error)] if error.http_status and error.http_status < 500 else [],
            "data": {"id": None, "awb_number": None},
            "payload": summary,
        }

    raw = booking.raw_response if isinstance(booking.raw_response, dict) else {}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    return {
        "outcome": "success",
        "http_status": raw.get("http_status", 200),
        "message": raw.get("message"),
        "validation_errors": raw.get("errors") if isinstance(raw.get("errors"), (dict, list)) else None,
        "data": {"id": data.get("id"), "awb_number": data.get("awb_number")},
        "payload": summary,
    }
