from datetime import datetime
from io import BytesIO
import re
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.orders import ShopifyOrder
from app.repositories.shiprocket import get_shipment, get_shipments_by_order_id, snapshot as shipment_snapshot
from app.services.order_operations import OrderOperationsStore
from app.services.delhivery import DelhiveryError, DelhiveryService
from app.services.shipment_status import derive_operational_status
from app.services.shiprocket import ShiprocketAPIError, ShiprocketConfigurationError, ShiprocketService
from app.services.shopify import ShopifyConfigurationError, ShopifyService, ShopifySyncError
from app.services.shopify_fulfillment import ShopifyFulfillmentSynchronizer, ShopifyFulfillmentSyncError

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
    update_customer_address: bool = True
    one_time_delivery_address: bool = False
    use_as_default_address: bool = False


class CallLogPayload(BaseModel):
    result: str = Field(...)
    timestamp: str | None = None
    operator: str = Field(...)
    comment: str | None = None


class VerifyAddressPayload(BaseModel):
    operator: str = Field(...)
    verified_at: str | None = None
    address_snapshot: dict[str, str | None] = Field(default_factory=dict)


class ExportPayload(BaseModel):
    mode: str = "current"
    order_ids: list[str] = Field(default_factory=list)


class AddressValidationPayload(BaseModel):
    address_line1: str | None = None
    address_line2: str | None = None
    landmark: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None


def _merged_operational_state(order: ShopifyOrder, operations: dict[str, object]) -> ShopifyOrder:
    call_logs = operations.get("call_logs") or []
    human_actions = operations.get("human_actions") or []
    first_action_at = operations.get("first_action_at")
    if not first_action_at and call_logs:
        first_action_at = min((str(value.get("timestamp")) for value in call_logs if value.get("timestamp")), default=None)
    if not first_action_at and any((operations.get("corrected_address"), operations.get("address_verified"), operations.get("package_details"), operations.get("selected_courier"))):
        first_action_at = "historic"

    # Single authoritative precedence chain - see app/services/shipment_status.py. Shipment/
    # fulfilment-backed states (Cancelled, Delivered, Shipped, Booked, NDR) always outrank
    # locally-derived operational states, so call logs/address edits can never downgrade them.
    operational_status = derive_operational_status(order, operations, operations.get("shipment"))
    latest_call = call_logs[0]["result"] if call_logs else None

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
        "address_sync_results": operations.get("address_sync_results"),
        "package_details": operations.get("package_details"),
        "selected_courier": operations.get("selected_courier"),
        "shipment": operations.get("shipment"),
        "first_action_at": first_action_at,
        "human_action_count": len(human_actions) or (1 if first_action_at else 0),
        "call_attempt_count": len(call_logs),
    })


@router.get("", response_model=list[ShopifyOrder])
async def list_orders(db: Session = Depends(get_db)) -> list[ShopifyOrder]:
    """Return the latest Shopify orders through a read-only integration."""
    try:
        orders = await ShopifyService().get_latest_orders(force_refresh=True)
        operations_map = OrderOperationsStore.all()
        shipments = get_shipments_by_order_id(db)
        merged_orders: list[ShopifyOrder] = []
        for order in orders:
            shipment = shipments.get(order.order_id)
            operations = {**operations_map.get(order.order_id, {}), "shipment": shipment_snapshot(shipment) if shipment else None}
            merged_orders.append(_merged_operational_state(order, operations))
        return merged_orders
    except ShopifyConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except httpx.HTTPStatusError as error:
        raise HTTPException(status_code=502, detail="Shopify could not provide orders. Check the store, token, and API version.") from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Unable to reach Shopify.") from error


@router.get("/{order_id}/operations")
async def get_order_operations(order_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    operations = OrderOperationsStore.get(order_id)
    shipment = get_shipment(db, order_id)
    if shipment is not None:
        operations = {**operations, "shipment": shipment_snapshot(shipment)}
    return operations


@router.post("/{order_id}/shopify-fulfillment/sync")
async def sync_shopify_fulfillment(order_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    """Idempotently create or repair Shopify fulfillment tracking for a booked shipment."""
    try:
        result = await ShopifyFulfillmentSynchronizer().sync(
            db, order_id, f"gid://shopify/Order/{order_id}"
        )
        return {"order_id": order_id, "shipment": result}
    except ShopifyFulfillmentSyncError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{order_id}/address/validate")
async def validate_order_address(order_id: str, payload: AddressValidationPayload, db: Session = Depends(get_db)) -> dict[str, object]:
    text = " ".join(filter(None, [payload.address_line1, payload.address_line2, payload.landmark])).strip()
    pincode = str(payload.pincode or "").strip()
    blockers: list[str] = []
    warnings: list[str] = []
    if not text:
        blockers.append("Address is blank")
    if not pincode:
        blockers.append("Pincode required")
    elif not re.fullmatch(r"\d{6}", pincode):
        blockers.append("Pincode must contain exactly six digits")
    if text and not re.search(r"\b(?:house|flat|plot|door|h\.?\s*no|\d+[A-Za-z/-]*)\b", text, re.IGNORECASE):
        warnings.append("House or flat number was not detected")
    if text and len(text) < 18:
        warnings.append("Address looks unusually short")
    if not payload.landmark:
        warnings.append("Landmark is missing")
    pieces = [value.casefold().strip() for value in (payload.address_line1, payload.address_line2) if value]
    if len(pieces) == 2 and pieces[0] == pieces[1]:
        warnings.append("Duplicate address text exists")
    shipment = get_shipment(db, order_id)
    # address_confidence_score/category/source (see ShiprocketShipment model) are always None
    # today. Investigated 2026-07-21: none of the Shiprocket Shipping API v1 endpoints this app
    # calls (auth/login, settings/company/pickup, courier/serviceability, orders/create/adhoc,
    # courier/assign/awb, orders search, courier/track/awb, courier/generate/label,
    # courier/awb/update - see app/services/shiprocket.py) return an address-confidence-like
    # field in their response payloads. A confidence/quality score does exist, but only under
    # Shiprocket's separate "Sense" product (Address Score / SenseAddress APIs, sense.shiprocket.in
    # per public docs) - a different, separately-licensed API with its own credentials that this
    # app does not integrate with. Do not fabricate a value here; leave these columns null until
    # Sense (or an equivalent documented endpoint) is actually integrated. The columns/API fields/
    # UI below are kept in place so a real score can be wired in later without a schema change.
    score = shipment.address_confidence_score if shipment else None
    category = shipment.address_confidence_category if shipment else None
    return {
        "valid": not blockers,
        "status": "Pincode required" if blockers else "Address has warnings" if warnings else "Address looks complete",
        "blockers": blockers,
        "warnings": warnings,
        "shiprocket_confidence_score": score,
        "shiprocket_confidence_category": category,
        "shiprocket_confidence_source": shipment.address_confidence_source if shipment else None,
        "shiprocket_message": "Shiprocket score not available" if score is None else f"Shiprocket confidence: {score:g}%" + (f" - {category}" if category else ""),
    }


def _export_row(order: ShopifyOrder) -> list[object]:
    india = ZoneInfo("Asia/Kolkata")
    created = datetime.fromisoformat(order.created_date.replace("Z", "+00:00")).astimezone(india)
    address = order.corrected_address or (order.shipping_address.model_dump() if order.shipping_address else {})
    shipment = order.shipment or {}
    return [
        order.order_number, created.date(), created.time().replace(second=0, microsecond=0), order.customer_name,
        order.phone, address.get("city"), address.get("state"), address.get("pincode"), float(order.order_total),
        float(order.paid_amount), float(order.cod_collectable_amount), order.payment_type, order.payment_status,
        "High" if "high risk" in " ".join(order.tags).casefold() else "Low", "Repeat" if (order.customer_orders_count or 0) > 1 else "New",
        order.operational_status, order.call_attempt_count, "Verified" if order.address_verified else "Pending",
        shipment.get("address_confidence_score"), shipment.get("address_confidence_category"), shipment.get("provider"),
        shipment.get("courier_name"), shipment.get("awb"), shipment.get("latest_status"), shipment.get("booked_at"),
        shipment.get("label_print_status"), shipment.get("label_last_printed_at"),
    ]


@router.post("/export")
async def export_orders(payload: ExportPayload, db: Session = Depends(get_db)):
    orders = await list_orders(db)
    selected = orders if payload.mode == "full" else [order for order in orders if order.order_id in set(payload.order_ids)]
    headers = ["Order Number", "Order Date", "Order Time", "Customer", "Phone", "City", "State", "Pincode", "Total Value", "Amount Paid", "COD / Outstanding", "Payment Type", "Financial Status", "Risk", "Customer Type", "Operational Status", "Call Attempts", "Address Verification", "Address Confidence", "Address Category", "Courier Provider", "Courier", "AWB", "Shipment Status", "Booking Time", "Label Print Status", "Last Printed Time"]
    workbook = Workbook()
    workbook.remove(workbook.active)

    def add_sheet(name: str, values: list[ShopifyOrder]) -> None:
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for value in values:
            sheet.append(_export_row(value))
        if sheet.max_row >= 2:
            for column in (9, 10, 11):
                for cells in sheet.iter_cols(min_col=column, max_col=column, min_row=2, max_row=sheet.max_row):
                    cells[0].number_format = '₹#,##0.00'
        sheet.freeze_panes = "A2"

    if payload.mode == "full":
        summary = workbook.create_sheet("Summary")
        fresh = [value for value in orders if not value.first_action_at and not value.cancelled_at]
        pending_booking = [value for value in orders if value.operational_status == "Ready for Booking" and not (value.shipment or {}).get("awb")]
        summary.append(["Metric", "Count"])
        for metric, count in (("All Orders", len(orders)), ("Fresh Orders", len(fresh)), ("Pending Booking", len(pending_booking))):
            summary.append([metric, count])
        previous = [value for value in orders if value.first_action_at and value.operational_status not in {"Ready for Booking", "Booked", "Shipped", "Delivered", "Cancelled"}]
        tabs = {
            "All Orders": orders, "Fresh Orders": fresh, "Previous Pending": previous,
            "Pending Booking": pending_booking,
            "COD": [value for value in orders if value.payment_type in {"cod", "partial_cod"}],
            "Partial COD": [value for value in orders if value.payment_type == "partial_cod"],
            "Prepaid": [value for value in orders if value.payment_type == "prepaid"],
            "High Risk": [value for value in orders if "high risk" in " ".join(value.tags).casefold()],
            "Repeat Customers": [value for value in orders if (value.customer_orders_count or 0) > 1],
        }
        for name, values in tabs.items():
            add_sheet(name, values)
    else:
        add_sheet("Current View", selected)
    output = BytesIO()
    workbook.save(output)
    timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d-%H%M")
    return StreamingResponse(iter([output.getvalue()]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="mumchies-orders-{timestamp}.xlsx"'})


async def _official_shipping_label(order_id: str, db: Session, *, inline: bool = False, print_ready: bool = False):
    try:
        shipment = get_shipment(db, order_id)
        if shipment is None:
            raise HTTPException(status_code=404, detail="No courier shipment exists for this order.")
        if not shipment.awb:
            raise HTTPException(status_code=404, detail="No AWB exists for this shipment.")
        if shipment.provider == "delhivery":
            if shipment.booking_status != "booked":
                raise HTTPException(status_code=409, detail="The Delhivery shipment is not yet manifested and label-eligible.")
            response = await DelhiveryService().label(shipment.awb)
            reference = shipment.provider_order_id or order_id
            filename = f"delhivery-{reference}-{shipment.awb}.pdf"
        else:
            if not shipment.shipment_id:
                raise HTTPException(status_code=404, detail="No Shiprocket shipment ID exists for this order.")
            response = await ShiprocketService().fetch_label(shipment.shipment_id)
            filename = f"shipping-label-{shipment.awb}.pdf"
        content = response.content
        if print_ready:
            from app.services.label_printing import LabelPrintError, print_ready_pdf
            try:
                content = print_ready_pdf(content)
            except LabelPrintError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
        return StreamingResponse(
            iter([content]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{filename}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except DelhiveryError as error:
        status_code = 503 if error.status_code in {401, 403} else 502
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/{order_id}/shipment/label")
async def get_provider_shipping_label(order_id: str, disposition: str = "attachment", print_ready: bool = False, db: Session = Depends(get_db)):
    """Proxy the courier provider's official PDF bytes without re-rendering them."""
    if disposition not in {"attachment", "inline"}:
        raise HTTPException(status_code=400, detail="Label disposition must be attachment or inline.")
    return await _official_shipping_label(order_id, db, inline=disposition == "inline", print_ready=print_ready)


@router.get("/{order_id}/shipping-label")
async def get_shipping_label(order_id: str, db: Session = Depends(get_db)):
    """Backward-compatible alias for existing clients."""
    return await _official_shipping_label(order_id, db)


@router.put("/{order_id}/address")
async def update_order_address(order_id: str, payload: AddressPayload, db: Session = Depends(get_db)) -> dict[str, object]:
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
    # Local correction is intentionally committed before any external write.
    OrderOperationsStore.save_address(
        order_id,
        address,
        courier_sync_status=payload.courier_sync_status,
        courier_sync_error=payload.courier_sync_error,
    )
    results: dict[str, object] = {
        "shopify_order": "failed",
        "shopify_customer": "not_applicable",
        "shiprocket": "not_applicable",
        "delhivery": "not_applicable",
        "errors": {},
    }
    service = ShopifyService()
    context: dict[str, object] | None = None
    try:
        context = await service.get_order_address_context(order_id)
    except (ShopifySyncError, httpx.HTTPError) as error:
        results["errors"]["shopify_order"] = str(error)
        if payload.update_customer_address and not payload.one_time_delivery_address:
            results["shopify_customer"] = "failed"
            results["errors"]["shopify_customer"] = "Customer address could not be resolved because the Shopify order lookup failed."
    if context is not None:
        try:
            await service.update_order_shipping_address(order_id, address)
            results["shopify_order"] = "synced"
        except (ShopifySyncError, httpx.HTTPError) as error:
            results["errors"]["shopify_order"] = str(error)

        update_customer = payload.update_customer_address and not payload.one_time_delivery_address
        customer_id = context.get("customer_id")
        if update_customer and customer_id:
            try:
                await service.update_customer_address(
                    str(customer_id),
                    context.get("shipping_address") if isinstance(context.get("shipping_address"), dict) else {},
                    address,
                    set_as_default=payload.use_as_default_address,
                )
                results["shopify_customer"] = "synced"
            except (ShopifySyncError, httpx.HTTPError) as error:
                results["shopify_customer"] = "failed"
                results["errors"]["shopify_customer"] = str(error)
        else:
            results["shopify_customer"] = "not_applicable"

    shipment = get_shipment(db, order_id)
    if shipment and shipment.awb and shipment.provider == "shiprocket":
        courier_address = {
            "shipping_customer_name": address["customer_name"],
            "shipping_phone": address["phone"],
            "shipping_address": address["address_line1"],
            "shipping_address_2": " ".join(filter(None, [address["address_line2"], address["landmark"]])),
            "shipping_city": address["city"],
            "shipping_state": address["state"],
            "shipping_pincode": address["pincode"],
        }
        try:
            await ShiprocketService().update_address(shipment.awb, courier_address)
            results["shiprocket"] = "synced"
        except (ShiprocketConfigurationError, ShiprocketAPIError, httpx.HTTPError) as error:
            results["shiprocket"] = "failed"
            results["errors"]["shiprocket"] = str(error)
    elif shipment and shipment.awb and shipment.provider == "delhivery":
        results["delhivery"] = "manual_required"
        results["errors"]["delhivery"] = "The booked Delhivery shipment was not changed automatically; cancellation/rebooking may be required."

    return OrderOperationsStore.save_address_sync_results(order_id, results)


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
