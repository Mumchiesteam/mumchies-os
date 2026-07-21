from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.shiprocket import get_shipment, snapshot as shipment_snapshot, upsert_shipment
from app.schemas.orders import ShopifyOrder
from app.services.order_operations import OrderOperationsStore
from app.services.delhivery import DelhiveryError, DelhiveryService, shadowfax_zone_d_quote
from app.services.shipment_status import has_existing_shipment_evidence
from app.services.shiprocket import (
    BookingEligibilityResult,
    CourierQuote,
    ShiprocketAPIError,
    ShiprocketConfigurationError,
    ShiprocketService,
)
from app.services.shopify import ShopifyConfigurationError, ShopifyService
from app.services.shopify_fulfillment import ShopifyFulfillmentSynchronizer, ShopifyFulfillmentSyncError

router = APIRouter(prefix="/couriers/shiprocket", tags=["couriers"])
booking_router = APIRouter(prefix="/orders", tags=["couriers"])


class PackageDetailsPayload(BaseModel):
    weight_kg: float = Field(gt=0)
    length_cm: float = Field(default=5, gt=0)
    breadth_cm: float = Field(default=5, gt=0)
    height_cm: float = Field(default=5, gt=0)


class CourierCheckPayload(PackageDetailsPayload):
    courier_payment_mode: str = Field(default="COD")


class BookingPayload(PackageDetailsPayload):
    courier_id: str
    provider: str | None = None
    courier_name: str | None = None


async def _sync_shopify_after_booking(db: Session, order: ShopifyOrder) -> dict[str, object] | None:
    """Best-effort secondary sync; courier persistence is never rolled back."""
    shipment = get_shipment(db, order.order_id)
    if shipment is None or not shipment.awb:
        return shipment_snapshot(shipment) if shipment else None
    try:
        return await ShopifyFulfillmentSynchronizer().sync(
            db, order.order_id, order.shopify_graphql_id
        )
    except ShopifyFulfillmentSyncError:
        return shipment_snapshot(get_shipment(db, order.order_id))


def _activate_new_label_tracking(db: Session, order_id: str, booking_result: dict[str, object]) -> None:
    if booking_result.get("existing"):
        return
    shipment = get_shipment(db, order_id)
    if shipment and shipment.awb and shipment.booking_status == "booked" and shipment.label_print_status is None:
        upsert_shipment(
            db, order_id, label_print_status="not_printed", label_print_count=0,
            label_tracking_activated_at=datetime.now(timezone.utc),
        )


async def _load_order(order_id: str) -> ShopifyOrder:
    orders = await ShopifyService().get_latest_orders()
    for order in orders:
        if order.order_id == order_id:
            return order
    raise HTTPException(status_code=404, detail="Order not found in Shopify.")


async def _load_context(order_id: str, db: Session) -> tuple[ShopifyOrder, dict[str, object], dict[str, object] | None]:
    order = await _load_order(order_id)
    operations = OrderOperationsStore.get(order_id)
    shipment = get_shipment(db, order_id)
    return order, operations, shipment_snapshot(shipment) if shipment else None


async def _serviceability_query(order: ShopifyOrder, operations: dict[str, object], package: PackageDetailsPayload, payment_mode: str) -> tuple[str, str, bool]:
    service = ShiprocketService()
    pickup_details = await service.pickup_location_details()
    pickup_postcode = str(
        (pickup_details or {}).get("postal_code")
        or (pickup_details or {}).get("pincode")
        or (pickup_details or {}).get("pin_code")
        or ""
    ).strip()
    address = operations.get("corrected_address") or operations.get("verified_address_snapshot") or (order.shipping_address.model_dump() if order.shipping_address else None)
    delivery_postcode = None
    if isinstance(address, dict):
        delivery_postcode = str(address.get("pincode") or "").strip() or None
    if not pickup_postcode:
        raise HTTPException(status_code=400, detail="Pickup postcode could not be resolved from Shiprocket pickup configuration.")
    if not delivery_postcode:
        raise HTTPException(status_code=400, detail="Delivery postcode is missing.")
    cod = payment_mode.upper() == "COD"
    return pickup_postcode, delivery_postcode, cod


def _order_payment_mode(order: ShopifyOrder) -> str:
    return "COD" if order.payment_type in {"cod", "partial_cod"} else "Prepaid"


def _order_latest_address(order: ShopifyOrder, operations: dict[str, object]) -> dict[str, object] | None:
    return operations.get("corrected_address") or operations.get("verified_address_snapshot") or (order.shipping_address.model_dump() if order.shipping_address else None)


def _build_shiprocket_order_payload(order: ShopifyOrder, operations: dict[str, object], package: PackageDetailsPayload) -> dict[str, object]:
    address = _order_latest_address(order, operations)
    if not isinstance(address, dict):
        raise HTTPException(status_code=400, detail="Latest operational address is missing.")
    name = str(address.get("customer_name") or order.customer_name or "").strip()
    name_parts = name.split(maxsplit=1)
    first_name = name_parts[0] if name_parts else "Customer"
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    phone = str(address.get("phone") or order.phone or "").strip()
    postcode = str(address.get("pincode") or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="Customer phone number is missing.")
    if not postcode:
        raise HTTPException(status_code=400, detail="Delivery postcode is missing.")

    required_address = {
        "address line 1": address.get("address_line1") or address.get("address"),
        "city": address.get("city"),
        "state": address.get("state"),
    }
    missing_address = [label for label, value in required_address.items() if not str(value or "").strip()]
    if missing_address:
        raise HTTPException(status_code=400, detail=f"Shipping address is missing: {', '.join(missing_address)}.")
    try:
        order_date = datetime.fromisoformat(order.created_date.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Shopify order date is invalid.") from error

    order_items = []
    for index, item in enumerate(order.products):
        if item.quantity <= 0 or float(item.price) < 0 or not item.product_name.strip():
            raise HTTPException(status_code=400, detail=f"Product line {index + 1} is invalid.")
        order_items.append(
            {
                "name": item.product_name,
                "sku": item.sku or f"ITEM-{index + 1}",
                "units": item.quantity,
                "selling_price": float(item.price),
                "discount": 0,
                "tax": 0,
                "hsn": "",
            }
        )

    return {
        "order_id": order.order_number,
        "order_date": order_date,
        "pickup_location": ShiprocketService().pickup_location,
        "billing_customer_name": first_name,
        "billing_last_name": last_name,
        "billing_address": address.get("address_line1") or address.get("address") or "",
        "billing_address_2": address.get("address_line2") or "",
        "billing_city": address.get("city") or "",
        "billing_pincode": postcode,
        "billing_state": address.get("state") or "",
        "billing_country": "India",
        "billing_email": order.email or "",
        "billing_phone": phone,
        "shipping_is_billing": True,
        "shipping_customer_name": first_name,
        "shipping_last_name": last_name,
        "shipping_address": address.get("address_line1") or address.get("address") or "",
        "shipping_address_2": address.get("address_line2") or "",
        "shipping_city": address.get("city") or "",
        "shipping_pincode": postcode,
        "shipping_country": "India",
        "shipping_state": address.get("state") or "",
        "shipping_email": order.email or "",
        "shipping_phone": phone,
        "order_items": order_items,
        "payment_method": "Prepaid" if _order_payment_mode(order) == "Prepaid" else "COD",
        "sub_total": float(order.cod_collectable_amount if order.payment_type == "partial_cod" else order.order_total),
        "length": package.length_cm,
        "breadth": package.breadth_cm,
        "height": package.height_cm,
        "weight": package.weight_kg,
    }


def _build_delhivery_payload(order: ShopifyOrder, operations: dict[str, object], package: PackageDetailsPayload) -> dict[str, object]:
    address = _order_latest_address(order, operations)
    if not isinstance(address, dict):
        raise HTTPException(status_code=400, detail="Latest operational address is missing.")
    phone = str(address.get("phone") or order.phone or "").strip()
    postcode = str(address.get("pincode") or "").strip()
    if not phone or not postcode:
        raise HTTPException(status_code=400, detail="Customer phone and delivery postcode are required.")
    if not postcode.isdigit() or len(postcode) != 6:
        raise HTTPException(status_code=400, detail="Delivery postcode must contain exactly 6 digits.")
    payment_mode = _order_payment_mode(order)
    if payment_mode not in {"COD", "Prepaid"}:
        raise HTTPException(status_code=400, detail="Payment mode is not supported by Delhivery.")
    if payment_mode == "COD" and float(order.cod_collectable_amount) <= 0:
        raise HTTPException(status_code=400, detail="COD amount must be greater than zero.")
    description = ", ".join(item.product_name for item in order.products)[:250]
    return {
        "name": str(address.get("customer_name") or order.customer_name or "Customer"),
        "add": " ".join(filter(None, [address.get("address_line1") or address.get("address"), address.get("address_line2"), address.get("landmark")])),
        "pin": postcode,
        "city": address.get("city") or "",
        "state": address.get("state") or "",
        "country": "India",
        "phone": phone,
        "order": order.order_number,
        "payment_mode": payment_mode,
        "cod_amount": float(order.cod_collectable_amount) if payment_mode == "COD" else 0,
        "total_amount": float(order.order_total),
        "products_desc": description,
        "quantity": sum(item.quantity for item in order.products),
        "weight": max(round(package.weight_kg * 1000), 1),
        "shipment_width": package.breadth_cm,
        "shipment_length": package.length_cm,
        "shipment_height": package.height_cm,
        "shipping_mode": "Surface",
        "address_type": "home",
    }


@router.get("/health")
async def shiprocket_health() -> dict[str, object]:
    try:
        result = await ShiprocketService().health()
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        return {
            "provider": "shiprocket",
            "configured": True,
            "authenticated": False,
            "pickup_exists": False,
            "pickup_location": None,
            "message": "Shiprocket authentication failed.",
            "error": str(error),
        }
    except httpx.HTTPError:
        return {
            "provider": "shiprocket",
            "configured": True,
            "authenticated": False,
            "pickup_exists": False,
            "pickup_location": None,
            "message": "Unable to reach Shiprocket.",
        }

    return {
        "provider": "shiprocket",
        "configured": result.configured,
        "authenticated": result.authenticated,
        "pickup_exists": result.pickup_exists,
        "pickup_location": result.pickup_location,
        "message": result.message,
    }


@router.post("/orders/{order_id}/package")
async def save_package_details(order_id: str, payload: PackageDetailsPayload) -> dict[str, object]:
    record = OrderOperationsStore.save_package_details(order_id, payload.model_dump())
    return {"provider": "shiprocket", "package_details": record.get("package_details")}


@router.get("/orders/{order_id}/eligibility")
async def booking_eligibility(order_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    order, operations, shipment = await _load_context(order_id, db)
    result = ShiprocketService().evaluate_booking_eligibility(order, operations, shipment)
    return {
        "provider": "shiprocket",
        "eligible": result.eligible,
        "missing_requirements": result.missing_requirements,
        "operational_status": result.operational_status,
        "payment_mode": result.payment_mode,
        "shipment_exists": result.shipment_exists,
        "shipment_status": result.shipment_status,
        "shipment": result.shipment_snapshot,
    }


@router.post("/orders/{order_id}/couriers/check")
async def shiprocket_serviceability(order_id: str, payload: CourierCheckPayload, db: Session = Depends(get_db)) -> dict[str, object]:
    provider_warnings: list[str] = []
    try:
        order, operations, shipment = await _load_context(order_id, db)
        package = PackageDetailsPayload.model_validate(payload.model_dump())
        OrderOperationsStore.save_package_details(order_id, package.model_dump())
        eligibility = ShiprocketService().evaluate_booking_eligibility(order, operations, shipment)
        if not eligibility.eligible:
            raise HTTPException(status_code=400, detail={"message": "Order is not eligible for courier lookup.", "missing_requirements": eligibility.missing_requirements})
        pickup_postcode, delivery_postcode, cod = await _serviceability_query(order, operations, package, payload.courier_payment_mode)
        quotes = await ShiprocketService().serviceability(pickup_postcode, delivery_postcode, package.weight_kg, cod)
        normalized_quotes = [asdict(quote) for quote in quotes]
        delhivery = DelhiveryService()
        try:
            if delhivery.configured:
                direct_quotes = await delhivery.serviceability(pickup_postcode, delivery_postcode, package.weight_kg, cod)
                normalized_quotes.extend(asdict(quote) for quote in direct_quotes)
            else:
                provider_warnings.append("Direct Delhivery booking is not configured.")
        except (DelhiveryError, httpx.HTTPError):
            # One provider failing must not hide otherwise valid courier options.
            provider_warnings.append("Direct Delhivery is temporarily unavailable.")
        normalized_quotes.append(shadowfax_zone_d_quote(cod))
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {
        "provider": "multi",
        "pickup_postcode": pickup_postcode,
        "delivery_postcode": delivery_postcode,
        "payment_mode": "COD" if cod else "Prepaid",
        "weight_kg": package.weight_kg,
        "provider_warnings": provider_warnings,
        "couriers": sorted(normalized_quotes, key=lambda quote: float(quote["total_estimated_shipping_cost"])),
    }


@router.post("/orders/{order_id}/book")
async def shiprocket_book_shipment(order_id: str, payload: BookingPayload, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        order, operations, shipment = await _load_context(order_id, db)
        package = PackageDetailsPayload.model_validate(payload.model_dump())
        existing = get_shipment(db, order_id)
        if existing and (existing.awb or existing.shipment_id or existing.shiprocket_order_id):
            return {"provider": existing.provider or "shiprocket", "existing": True, "shipment": shipment_snapshot(existing)}

        # Backend duplicate-booking guard: reject outright (not just via eligibility) if any
        # reliable source - local shipment, Shopify fulfilment status/tags - already shows an
        # active shipment. Applies uniformly to every provider, not just Delhivery.
        if has_existing_shipment_evidence(order, operations, shipment):
            raise HTTPException(
                status_code=409,
                detail="An active shipment or fulfilment already exists for this order. Booking is blocked to prevent a duplicate shipment.",
            )

        eligibility = ShiprocketService().evaluate_booking_eligibility(order, operations, shipment)
        if not eligibility.eligible:
            raise HTTPException(status_code=400, detail={"message": "Order is not eligible for booking.", "missing_requirements": eligibility.missing_requirements})
        selected = operations.get("selected_courier")
        if not isinstance(selected, dict) or str(selected.get("courier_id") or "") != str(payload.courier_id):
            raise HTTPException(status_code=400, detail="Selected courier does not match the stored courier selection.")

        provider = str(selected.get("provider") or "shiprocket").lower()
        if payload.provider and payload.provider.lower() != provider:
            raise HTTPException(status_code=400, detail="Requested provider does not match the stored courier selection.")
        if provider == "shadowfax":
            raise HTTPException(status_code=409, detail="Shadowfax booking is manual. Use the displayed Zone D estimate in the Shadowfax portal.")
        if provider == "delhivery":
            service = DelhiveryService()
            if not service.configured:
                raise HTTPException(status_code=503, detail="Direct Delhivery booking is not configured. DELHIVERY_TOKEN and DELHIVERY_PICKUP are required.")
            if not bool(selected.get("booking_supported")):
                raise HTTPException(status_code=409, detail="The selected Delhivery service is not available for direct booking.")
            if order.cancelled_at:
                raise HTTPException(status_code=409, detail="Cancelled orders cannot be booked with Delhivery.")
            fulfillment = str(order.fulfillment_status or "").strip().casefold()
            if fulfillment in {"fulfilled", "shipped", "delivered", "in_transit", "in transit"}:
                raise HTTPException(status_code=409, detail="Fulfilled or shipped orders cannot be booked with Delhivery.")
            result = await service.book_order_shipment(
                db, order_id, order.order_number,
                _build_delhivery_payload(order, operations, package),
                package.model_dump(), payload.courier_id,
                str(selected.get("courier_name") or "Delhivery Surface"),
            )
            OrderOperationsStore.save_selected_courier(order_id, selected)
            _activate_new_label_tracking(db, order_id, result)
            synchronized = await _sync_shopify_after_booking(db, order)
            return {"provider": "delhivery", **result, "shipment": synchronized or result.get("shipment")}

        order_payload = _build_shiprocket_order_payload(order, operations, package)
        service = ShiprocketService()
        result = await service.book_order_shipment(
            db,
            order_id,
            order_payload,
            courier_id=payload.courier_id,
            package_details=package.model_dump(),
            courier_name=str(selected.get("courier_name") or ""),
        )
        OrderOperationsStore.save_selected_courier(order_id, selected)
        _activate_new_label_tracking(db, order_id, result)
        synchronized = await _sync_shopify_after_booking(db, order)
        return {"provider": "shiprocket", **result, "shipment": synchronized or result.get("shipment")}
    except DelhiveryError as error:
        raise HTTPException(status_code=502, detail={"message": str(error), "upstream_status": error.status_code}) from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail={"message": "Unable to reach Delhivery. No automatic retry was attempted."}) from error
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"Shiprocket rejected the shipment: {error}",
                "upstream_status": error.status_code,
                **error.safe_details,
            },
        ) from error


@booking_router.post("/{order_id}/book")
async def provider_book_shipment(order_id: str, payload: BookingPayload, db: Session = Depends(get_db)) -> dict[str, object]:
    """Provider-neutral booking entrypoint; delegates to the existing guarded implementation."""
    return await shiprocket_book_shipment(order_id, payload, db)


@router.post("/orders/{order_id}/couriers/select")
async def select_courier(order_id: str, payload: dict[str, object]) -> dict[str, object]:
    provider = str(payload.get("provider") or "shiprocket").lower()
    selected = {
        "provider": provider,
        "booking_supported": provider in {"shiprocket", "delhivery"} and bool(payload.get("booking_supported", True)),
        "rate_note": str(payload.get("rate_note") or ""),
        "courier_id": str(payload.get("courier_id") or ""),
        "courier_name": str(payload.get("courier_name") or ""),
        "rate": payload.get("rate"),
        "cod_charge": payload.get("cod_charge"),
        "total_estimated_shipping_cost": payload.get("total_estimated_shipping_cost"),
        "estimated_delivery_days": payload.get("estimated_delivery_days"),
        "expected_delivery_date": payload.get("expected_delivery_date"),
        "rating": payload.get("rating"),
        "mode": payload.get("mode"),
    }
    record = OrderOperationsStore.save_selected_courier(order_id, selected)
    return {"provider": provider, "selected_courier": record.get("selected_courier")}


@router.get("/orders/{order_id}/tracking")
async def shiprocket_tracking(order_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.awb:
            raise HTTPException(status_code=404, detail="No Shiprocket shipment exists for this order.")
        if shipment.provider == "delhivery":
            refreshed = await DelhiveryService().reconcile(
                db, order_id,
                order_number=shipment.provider_order_id or order_id,
                waybill=shipment.awb,
            )
            return {"provider": "delhivery", "shipment": refreshed}
        return await ShiprocketService().sync_tracking(db, order_id, shipment.awb)
    except DelhiveryError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post("/orders/{order_id}/refresh")
async def refresh_shiprocket_shipment(order_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        order, _, _ = await _load_context(order_id, db)
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.shipment_id:
            raise HTTPException(status_code=404, detail="No existing courier shipment is available to refresh.")
        if shipment.provider == "delhivery":
            refreshed = await DelhiveryService().reconcile(
                db, order_id,
                order_number=shipment.provider_order_id or order.order_number,
                waybill=shipment.awb or shipment.shipment_id,
            )
            return {"provider": "delhivery", "shipment": refreshed}
        if shipment.provider != "shiprocket":
            raise HTTPException(status_code=409, detail="This courier provider does not support shipment refresh.")
        refreshed = await ShiprocketService().reconcile_existing_shipment(
            db,
            order_id,
            shipment.provider_order_id or order.order_number,
            shipment.shipment_id,
        )
        return {"provider": "shiprocket", "shipment": refreshed}
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail={"message": str(error), **error.safe_details}) from error
    except DelhiveryError as error:
        raise HTTPException(status_code=502, detail={"message": str(error), "upstream_status": error.status_code}) from error


@router.put("/orders/{order_id}/address")
async def shiprocket_update_address(order_id: str, payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.awb:
            raise HTTPException(status_code=404, detail="No Shiprocket shipment exists for this order.")
        service = ShiprocketService()
        result = await service.update_address(shipment.awb, payload)
        upsert_shipment(db, order_id, address_sync_status="updated", address_sync_error=None)
        return {"provider": "shiprocket", "updated": True, "response": result}
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        upsert_shipment(db, order_id, address_sync_status="failed", address_sync_error=str(error))
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/orders/{order_id}/shipping-label")
async def shiprocket_shipping_label(order_id: str, db: Session = Depends(get_db)):
    try:
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.awb or not shipment.shipment_id:
            raise HTTPException(status_code=404, detail="No Shiprocket shipment exists for this order.")
        response = await (DelhiveryService().label(shipment.awb) if shipment.provider == "delhivery" else ShiprocketService().fetch_label(shipment.shipment_id))
        content_type = response.headers.get("content-type", "application/pdf")
        return StreamingResponse(iter([response.content]), media_type=content_type)
    except DelhiveryError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
