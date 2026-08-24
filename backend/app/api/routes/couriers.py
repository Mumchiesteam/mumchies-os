from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib
import logging
import time
from copy import deepcopy

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.core.identity import current_actor, current_user
from app.repositories.shiprocket import get_shipment, snapshot as shipment_snapshot, upsert_shipment
from app.schemas.orders import ShopifyOrder
from app.services.order_operations import OrderOperationsStore
from app.services.delhivery import DelhiveryError, DelhiveryService
from app.services.courier_platform import ProviderError, courier_registry
from app.services.courier_platform.adapters import ShadowfaxAdapter
from app.services.courier_platform.shadowfax_http import reset_shadowfax_outbound_observer, set_shadowfax_outbound_observer
from app.services.courier_platform.service import CourierPlatformService
from app.services.shipment_status import has_existing_shipment_evidence, has_persisted_provider_booking_evidence, has_uncertain_provider_booking
from app.services.shiprocket import (
    BookingEligibilityResult,
    CourierQuote,
    ShiprocketAPIError,
    ShiprocketConfigurationError,
    ShiprocketPersistenceError,
    ShiprocketService,
)
from app.services.shopify import ShopifyConfigurationError, ShopifyService
from app.services.shopify_fulfillment import ShopifyFulfillmentSynchronizer, ShopifyFulfillmentSyncError
from app.services.temporary_shadowfax_repair import repair_legacy_shadowfax_test_324541

router = APIRouter(prefix="/couriers/shiprocket", tags=["couriers"])
booking_router = APIRouter(prefix="/orders", tags=["couriers"])
LOGGER = logging.getLogger(__name__)


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
    operator: str = "Mumchies OS"
    draft_order_id: str
    address_revision: int = Field(ge=0)
    booking_context_hash: str


class BookingPreviewPayload(PackageDetailsPayload):
    courier_id: str
    provider: str
    courier_name: str
    draft_order_id: str
    address_revision: int = Field(ge=0)


class BookingContext(BaseModel):
    model_config = {"frozen": True, "arbitrary_types_allowed": True}
    order_id: str
    order_number: str
    order: ShopifyOrder
    address: dict[str, object]
    address_source: str
    address_revision: int
    package: PackageDetailsPayload
    selected_courier: dict[str, object]
    context_hash: str


class ProviderActionPayload(BaseModel):
    operator: str = "Mumchies OS"


class ManualShadowfaxPayload(BaseModel):
    awb: str | None = None
    provider_id: str | None = None
    service_name: str | None = None
    booked_at: datetime | None = None
    freight: float | None = Field(default=None, ge=0)
    note: str | None = None


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


async def _run_post_booking_work(
    order_id: str, order_number: str, order_gid: str | None,
    provider: str, operator: str,
) -> None:
    """Persist visible, retryable downstream results without extending booking latency."""
    started = time.perf_counter()
    fulfillment_started = time.perf_counter()
    with SessionLocal() as background_db:
        try:
            await ShopifyFulfillmentSynchronizer().sync(background_db, order_id, order_gid)
        except ShopifyFulfillmentSyncError:
            # The synchronizer persists its actionable failure state on the shipment.
            pass
    fulfillment_ms = (time.perf_counter() - fulfillment_started) * 1000
    timeline_started = time.perf_counter()
    OrderOperationsStore.record_timeline_event(order_id, "shipment_booked", operator=operator, details={"provider": provider})
    timeline_ms = (time.perf_counter() - timeline_started) * 1000
    LOGGER.info(
        "post_booking order_id=%s provider=%s shopify_fulfillment_ms=%.2f timeline_ms=%.2f total_ms=%.2f",
        order_id, provider, fulfillment_ms, timeline_ms, (time.perf_counter() - started) * 1000,
    )


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
    try:
        return await ShopifyService().get_order(order_id)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Order not found in Shopify.") from error
        raise


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
    delivery_postcode = service.delivery_postcode(order, operations)
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


def _booking_context(order: ShopifyOrder, operations: dict[str, object], package: PackageDetailsPayload, selected: dict[str, object]) -> BookingContext:
    stored_package = operations.get("package_details")
    package_provenance = operations.get("package_provenance")
    package_revision = int(operations.get("package_revision") or 0)
    if not isinstance(stored_package, dict) or PackageDetailsPayload.model_validate(stored_package).model_dump() != package.model_dump():
        raise HTTPException(status_code=409, detail="Booking blocked: package data changed or is not associated with this order. Refresh courier options.")
    if not isinstance(package_provenance, dict) or str(package_provenance.get("order_id") or "") != order.order_id or int(package_provenance.get("revision") or -1) != package_revision:
        raise HTTPException(status_code=409, detail="Booking blocked: package provenance is missing or belongs to another order. Refresh courier options.")
    override = operations.get("corrected_address") or operations.get("verified_address_snapshot")
    revision = int(operations.get("address_revision") or 0)
    if override:
        provenance = operations.get("address_provenance")
        if not isinstance(provenance, dict) or str(provenance.get("order_id") or "") != order.order_id or int(provenance.get("revision") or -1) != revision:
            raise HTTPException(status_code=409, detail="Booking blocked: corrected address provenance is missing, stale, or belongs to another order. Reload and verify the address.")
        address, source = deepcopy(override), "verified_override"
    else:
        if not order.shipping_address:
            raise HTTPException(status_code=409, detail="Booking blocked: authoritative Shopify shipping address is missing.")
        address, source = order.shipping_address.model_dump(), "shopify"
    snapshot = {
        "order_id": order.order_id, "order_number": order.order_number,
        "customer": order.customer_name, "phone": order.phone,
        "address": address, "products": [item.model_dump(mode="json") for item in order.products],
        "order_value": str(order.order_total), "payment": order.payment_type,
        "cod": str(order.cod_collectable_amount), "package": package.model_dump(),
        "selected_courier": selected, "address_source": source, "address_revision": revision, "package_revision": package_revision,
    }
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
    return BookingContext(
        order_id=order.order_id, order_number=order.order_number, order=order.model_copy(deep=True),
        address=deepcopy(address), address_source=source, address_revision=revision,
        package=package.model_copy(deep=True), selected_courier=deepcopy(selected), context_hash=digest,
    )


def _context_operations(context: BookingContext) -> dict[str, object]:
    return {"corrected_address": deepcopy(context.address)}


def _assert_booking_payload(context: BookingContext, provider: str, payload: dict[str, object]) -> None:
    expected_products = ", ".join(item.product_name for item in context.order.products)[:250]
    expected_name = str(context.address.get("customer_name") or context.address.get("name") or context.order.customer_name or "")
    expected_phone = str(context.address.get("phone") or context.order.phone or "")
    expected_address = " ".join(filter(None, [context.address.get("address_line1") or context.address.get("address"), context.address.get("address_line2"), context.address.get("landmark")]))
    payment_mode = _order_payment_mode(context.order)
    failures: list[str] = []
    if provider == "delhivery":
        checks = {"order": context.order_number, "name": expected_name, "phone": expected_phone, "add": expected_address,
                  "pin": str(context.address.get("pincode") or ""), "city": context.address.get("city") or "", "state": context.address.get("state") or "",
                  "products_desc": expected_products, "payment_mode": payment_mode,
                  "quantity": sum(item.quantity for item in context.order.products), "total_amount": float(context.order.order_total),
                  "cod_amount": float(context.order.cod_collectable_amount) if payment_mode == "COD" else 0,
                  "weight": max(round(context.package.weight_kg * 1000), 1)}
    elif provider == "shiprocket":
        expected_items = [{"name": item.product_name, "sku": item.sku or f"ITEM-{index + 1}", "units": item.quantity, "selling_price": float(item.price), "discount": 0, "tax": 0, "hsn": ""} for index, item in enumerate(context.order.products)]
        name_parts = expected_name.split(maxsplit=1)
        checks = {"order_id": context.order_number, "shipping_customer_name": name_parts[0] if name_parts else "Customer",
                  "shipping_phone": expected_phone, "shipping_address": context.address.get("address_line1") or context.address.get("address") or "",
                  "shipping_city": context.address.get("city") or "", "shipping_state": context.address.get("state") or "",
                  "shipping_pincode": str(context.address.get("pincode") or ""), "order_items": expected_items,
                  "sub_total": float(context.order.cod_collectable_amount if context.order.payment_type == "partial_cod" else context.order.order_total),
                  "weight": context.package.weight_kg}
    else:
        details = payload.get("order_details") if isinstance(payload.get("order_details"), dict) else {}
        customer = payload.get("customer_details") if isinstance(payload.get("customer_details"), dict) else {}
        payload = {**details, "pincode": customer.get("pincode"), "customer_name": customer.get("name"), "phone": customer.get("contact"),
                   "address": customer.get("address_line_1"), "city": customer.get("city"), "state": customer.get("state"), "products": payload.get("product_details")}
        expected_shadowfax_products = [{"sku_name": item.product_name, "price": float(item.price), "additional_details": {"quantity": item.quantity}, **({"sku_id": item.sku} if item.sku else {})} for item in context.order.products]
        checks = {"client_order_id": context.order_number, "pincode": int(str(context.address.get("pincode") or "0")),
                  "customer_name": expected_name, "phone": expected_phone, "address": context.address.get("address_line1") or context.address.get("address"),
                  "city": context.address.get("city"), "state": context.address.get("state"), "products": expected_shadowfax_products,
                  "total_amount": float(context.order.order_total), "actual_weight": max(round(context.package.weight_kg * 1000), 1)}
    for field, expected in checks.items():
        if payload.get(field) != expected:
            failures.append(field)
    if failures:
        LOGGER.error("booking_integrity_block order_id=%s provider=%s fields=%s", context.order_id, provider, ",".join(failures))
        raise HTTPException(status_code=409, detail="Booking blocked: order data changed or could not be verified. Reload the order before booking.")


def _validate_shadowfax_booking_request(payload: dict[str, object]) -> None:
    """Fail locally before consuming a one-time provider request."""
    errors: list[str] = []
    order = payload.get("order_details") if isinstance(payload.get("order_details"), dict) else {}
    customer = payload.get("customer_details") if isinstance(payload.get("customer_details"), dict) else {}
    pickup = payload.get("pickup_details") if isinstance(payload.get("pickup_details"), dict) else {}
    rto = payload.get("rto_details") if isinstance(payload.get("rto_details"), dict) else {}
    products = payload.get("product_details") if isinstance(payload.get("product_details"), list) else []
    if payload.get("order_type") != "warehouse": errors.append("order_type")
    for field in ("client_order_id", "client_name", "product_value", "payment_mode", "cod_amount"):
        if order.get(field) in (None, ""): errors.append(f"order_details.{field}")
    if order.get("payment_mode") not in {"COD", "Prepaid"}: errors.append("order_details.payment_mode")
    if order.get("payment_mode") == "COD" and float(order.get("cod_amount") or 0) <= 0: errors.append("order_details.cod_amount")
    for field in ("actual_weight", "volumetric_weight"):
        if float(order.get(field) or 0) <= 0: errors.append(f"order_details.{field}")
    if order.get("order_service") != "regular": errors.append("order_details.order_service")
    for label, details, required in (
        ("customer_details", customer, ("name", "contact", "address_line_1", "city", "state", "pincode")),
        ("pickup_details", pickup, ("contact", "address_line_1", "city", "state", "pincode")),
        ("rto_details", rto, ("name", "contact", "address_line_1", "city", "state", "pincode")),
    ):
        for field in required:
            if details.get(field) in (None, ""): errors.append(f"{label}.{field}")
        phone = "".join(ch for ch in str(details.get("contact") or "") if ch.isdigit())
        if not 10 <= len(phone) <= 13: errors.append(f"{label}.contact")
        pin = str(details.get("pincode") or "")
        if not (pin.isdigit() and len(pin) == 6): errors.append(f"{label}.pincode")
    if not products: errors.append("product_details")
    for index, product in enumerate(products):
        if not isinstance(product, dict) or not str(product.get("sku_name") or "").strip(): errors.append(f"product_details[{index}].sku_name")
        if not isinstance(product, dict) or product.get("price") is None: errors.append(f"product_details[{index}].price")
        quantity = ((product.get("additional_details") or {}).get("quantity") if isinstance(product, dict) and isinstance(product.get("additional_details"), dict) else None)
        if not isinstance(quantity, int) or quantity <= 0: errors.append(f"product_details[{index}].additional_details.quantity")
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Shadowfax payload validation failed before provider request.", "fields": sorted(set(errors))})


def _build_shiprocket_order_payload(order: ShopifyOrder, operations: dict[str, object], package: PackageDetailsPayload) -> dict[str, object]:
    address = _order_latest_address(order, operations)
    if not isinstance(address, dict):
        raise HTTPException(status_code=400, detail="Latest operational address is missing.")
    name = str(address.get("customer_name") or order.customer_name or "").strip()
    name_parts = name.split(maxsplit=1)
    first_name = name_parts[0] if name_parts else "Customer"
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    phone = str(address.get("phone") or order.phone or "").strip()
    postcode = ShiprocketService.delivery_postcode(order, operations) or ""
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


async def _build_provider_booking_request(order: ShopifyOrder, operations: dict[str, object], package: PackageDetailsPayload) -> dict[str, object]:
    """Build the documented Shadowfax warehouse payload from existing OS data."""
    address = _order_latest_address(order, operations)
    if not isinstance(address, dict):
        raise HTTPException(status_code=400, detail="Latest operational address is missing.")
    phone = str(address.get("phone") or order.phone or "").strip()
    pincode = str(address.get("pincode") or "").strip()
    if not phone or not pincode:
        raise HTTPException(status_code=400, detail="Customer phone and delivery postcode are required.")
    if not pincode.isdigit() or len(pincode) != 6:
        raise HTTPException(status_code=400, detail="Delivery postcode must contain exactly 6 digits.")
    customer_name = str(address.get("customer_name") or address.get("name") or order.customer_name or "").strip()
    if not customer_name:
        raise HTTPException(status_code=400, detail="Customer name is required for Shadowfax booking.")
    customer_address = {
        "address_line_1": address.get("address_line1") or address.get("address"),
        "city": address.get("city"),
        "state": address.get("state"),
    }
    missing_customer = [field for field, value in customer_address.items() if not str(value or "").strip()]
    if missing_customer:
        raise HTTPException(status_code=400, detail=f"Shipping address is missing: {', '.join(missing_customer)}.")

    warehouse = await ShiprocketService().pickup_location_details()
    if not isinstance(warehouse, dict):
        raise HTTPException(status_code=400, detail="The configured Mumchies warehouse address could not be resolved.")

    def warehouse_value(*keys: str) -> str:
        return str(next((warehouse.get(key) for key in keys if warehouse.get(key) not in (None, "")), "")).strip()

    warehouse_pincode = warehouse_value("postal_code", "pincode", "pin_code")
    warehouse_details = {
        "name": warehouse_value("name", "pickup_location"),
        "contact": warehouse_value("phone", "contact", "mobile"),
        "address_line_1": warehouse_value("address", "address_1", "address_line_1"),
        "address_line_2": warehouse_value("address_2", "address_line_2"),
        "city": warehouse_value("city"),
        "state": warehouse_value("state"),
        "pincode": int(warehouse_pincode) if warehouse_pincode.isdigit() and len(warehouse_pincode) == 6 else None,
    }
    required_warehouse = ("name", "contact", "address_line_1", "city", "state", "pincode")
    missing_warehouse = [field for field in required_warehouse if not warehouse_details.get(field)]
    if missing_warehouse:
        raise HTTPException(
            status_code=400,
            detail=f"The configured Mumchies warehouse address is missing: {', '.join(missing_warehouse)}.",
        )

    product_details = []
    for index, item in enumerate(order.products):
        if item.quantity <= 0 or float(item.price) < 0 or not item.product_name.strip():
            raise HTTPException(status_code=400, detail=f"Product line {index + 1} is invalid.")
        product = {
            "sku_name": item.product_name,
            "price": float(item.price),
            "additional_details": {"quantity": item.quantity},
        }
        if item.sku:
            product["sku_id"] = item.sku
        product_details.append(product)

    payment_mode = _order_payment_mode(order)
    product_value = sum(float(item.price) * item.quantity for item in order.products)
    payload = {
        "order_type": "warehouse",
        "order_details": {
            "client_order_id": order.order_number,
            "client_name": "Mumchies Foods",
            "actual_weight": max(round(package.weight_kg * 1000), 1),
            "volumetric_weight": max(round((package.length_cm * package.breadth_cm * package.height_cm) / 5000 * 1000), 1),
            "product_value": product_value,
            "payment_mode": payment_mode,
            "cod_amount": float(order.cod_collectable_amount) if payment_mode == "COD" else 0,
            "total_amount": float(order.order_total),
            "order_service": "regular",
        },
        "customer_details": {
            "name": customer_name,
            "contact": phone,
            "address_line_1": customer_address["address_line_1"],
            "address_line_2": " ".join(filter(None, [address.get("address_line2"), address.get("landmark")])),
            "city": customer_address["city"],
            "state": customer_address["state"],
            "pincode": int(pincode),
        },
        "pickup_details": dict(warehouse_details),
        "rto_details": dict(warehouse_details),
        "product_details": product_details,
    }
    _validate_shadowfax_booking_request(payload)
    return payload


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
async def save_package_details(order_id: str, payload: PackageDetailsPayload, request: Request) -> dict[str, object]:
    record = OrderOperationsStore.save_package_details_with_timeline(order_id, payload.model_dump(), current_actor(request))
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
async def shiprocket_serviceability(order_id: str, payload: CourierCheckPayload, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    provider_warnings: list[str] = []
    provider_failures: dict[str, str] = {}
    request_started = time.perf_counter()
    context_started = request_started
    context_ms = pickup_ms = 0.0
    provider_timings: dict[str, float] = {}
    shiprocket_result: object = None
    delhivery_result: object = None
    try:
        order, operations, shipment = await _load_context(order_id, db)
        context_ms = (time.perf_counter() - context_started) * 1000
        # _load_context returns a detached dictionary snapshot. Release the
        # read transaction before waiting on provider networks.
        db.rollback()
        package = PackageDetailsPayload.model_validate(payload.model_dump())
        # Package persistence and stale-quote invalidation are one atomic operations-file
        # mutation. This preserves revisions/provenance while avoiding a second 15 MB rewrite.
        operations = OrderOperationsStore.prepare_courier_lookup(
            order_id, package.model_dump(), current_actor(request),
        )
        eligibility = ShiprocketService().evaluate_booking_eligibility(order, operations, shipment)
        if not eligibility.eligible:
            raise HTTPException(status_code=400, detail={"message": "Order is not eligible for courier lookup.", "missing_requirements": eligibility.missing_requirements})
        pickup_started = time.perf_counter()
        delivery_postcode = ShiprocketService().delivery_postcode(order, operations) or ""
        cod = payload.courier_payment_mode.upper() == "COD"
        try:
            pickup_postcode, delivery_postcode, cod = await asyncio.wait_for(
                _serviceability_query(order, operations, package, payload.courier_payment_mode), timeout=10.0,
            )
        except asyncio.TimeoutError:
            pickup_postcode = ""
            provider_failures["shiprocket"] = "pickup_timeout"
            provider_failures["delhivery"] = "pickup_unavailable"
        except (ShiprocketAPIError, ShiprocketConfigurationError, httpx.HTTPError, HTTPException):
            pickup_postcode = ""
            provider_failures["shiprocket"] = "pickup_unavailable"
            provider_failures["delhivery"] = "pickup_unavailable"
        pickup_ms = (time.perf_counter() - pickup_started) * 1000
        delhivery = DelhiveryService()
        async def shiprocket_quotes():
            if not pickup_postcode:
                return []
            started = time.perf_counter()
            try:
                return await asyncio.wait_for(
                    ShiprocketService().serviceability(pickup_postcode, delivery_postcode, package.weight_kg, cod), timeout=15.0,
                )
            finally:
                provider_timings["shiprocket"] = (time.perf_counter() - started) * 1000

        async def delhivery_quotes():
            if not pickup_postcode:
                return []
            if not delhivery.configured:
                provider_timings["delhivery"] = 0
                return None
            started = time.perf_counter()
            try:
                return await asyncio.wait_for(
                    delhivery.serviceability(pickup_postcode, delivery_postcode, package.weight_kg, cod), timeout=18.0,
                )
            finally:
                provider_timings["delhivery"] = (time.perf_counter() - started) * 1000

        shiprocket_result, delhivery_result = await asyncio.gather(
            shiprocket_quotes(), delhivery_quotes(), return_exceptions=True,
        )
        normalized_quotes = []
        if isinstance(shiprocket_result, Exception):
            provider_failures["shiprocket"] = "timeout" if isinstance(shiprocket_result, asyncio.TimeoutError) else "unavailable"
        else:
            normalized_quotes.extend(asdict(quote) for quote in shiprocket_result)
        if delhivery_result is None:
            provider_failures["delhivery"] = "not_configured"
            provider_warnings.append("Direct Delhivery booking is not configured.")
        elif isinstance(delhivery_result, Exception):
            provider_failures["delhivery"] = "timeout" if isinstance(delhivery_result, asyncio.TimeoutError) else "unavailable"
        else:
            normalized_quotes.extend(asdict(quote) for quote in delhivery_result)
        rate_provider_quotes = len(normalized_quotes)
        if "shiprocket" in provider_failures:
            provider_warnings.append("Shiprocket lookup failed. Available courier results are shown." if rate_provider_quotes else "Shiprocket lookup failed. Retry lookup.")
        if "delhivery" in provider_failures and provider_failures["delhivery"] != "not_configured":
            provider_warnings.append("Delhivery lookup failed. Available courier results are shown." if rate_provider_quotes else "Delhivery lookup failed. Retry lookup.")
        if all(provider in provider_failures for provider in ("shiprocket", "delhivery")):
            provider_warnings.append("Courier lookup failed: both rate providers are unavailable. Shadowfax manual remains available.")
        normalized_quotes.append({
            "courier_id": "shadowfax:manual", "courier_name": "Shadowfax", "rate": 0,
            "cod_charge": None, "total_estimated_shipping_cost": 0,
            "estimated_delivery_days": None, "expected_delivery_date": None, "rating": None,
            "cod_supported": True, "prepaid_supported": True, "mode": "Manual",
            "provider": "shadowfax", "booking_supported": True,
            "rate_note": "Manual booking on Shadowfax required",
        })
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    logging.getLogger(__name__).info(
        "courier_lookup total_ms=%.2f order_context_ms=%.2f pickup_ms=%.2f shiprocket_ms=%.2f delhivery_ms=%.2f shiprocket_ok=%s delhivery_ok=%s",
        (time.perf_counter() - request_started) * 1000, context_ms, pickup_ms,
        provider_timings.get("shiprocket", 0), provider_timings.get("delhivery", 0),
        not isinstance(shiprocket_result, Exception), not isinstance(delhivery_result, Exception),
    )
    return {
        "provider": "multi",
        "pickup_postcode": pickup_postcode,
        "delivery_postcode": delivery_postcode,
        "payment_mode": "COD" if cod else "Prepaid",
        "weight_kg": package.weight_kg,
        "provider_warnings": provider_warnings,
        "provider_failures": provider_failures,
        "lookup_status": "manual_only" if all(provider in provider_failures for provider in ("shiprocket", "delhivery")) else "partial" if provider_failures else "complete",
        "timings_ms": {
            "order_context": round(context_ms, 2), "pickup": round(pickup_ms, 2),
            "shiprocket": round(provider_timings.get("shiprocket", 0), 2),
            "delhivery": round(provider_timings.get("delhivery", 0), 2),
            "total_backend": round((time.perf_counter() - request_started) * 1000, 2),
        },
        "couriers": sorted(normalized_quotes, key=lambda quote: float(quote["total_estimated_shipping_cost"])),
        # This is the authoritative eligibility snapshot after package persistence.
        # The drawer must not keep using the pre-package snapshot that was loaded
        # when it first opened.
        "booking_readiness": {
            "eligible": eligibility.eligible,
            "missing_requirements": eligibility.missing_requirements,
            "operational_status": eligibility.operational_status,
            "payment_mode": eligibility.payment_mode,
            "shipment_exists": eligibility.shipment_exists,
            "shipment_status": eligibility.shipment_status,
            "shipment": eligibility.shipment_snapshot,
        },
    }


@router.post("/orders/{order_id}/book")
async def shiprocket_book_shipment_route(
    order_id: str, payload: BookingPayload, request: Request, background_tasks: BackgroundTasks,
    response: Response, db: Session = Depends(get_db),
) -> dict[str, object]:
    return await shiprocket_book_shipment(
        order_id, payload, db, current_actor(request), background_tasks=background_tasks, response=response,
    )


@booking_router.post("/{order_id}/shadowfax/manual")
async def save_manual_shadowfax_shipment(order_id: str, payload: ManualShadowfaxPayload, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    awb = str(payload.awb or "").strip() or None
    provider_id = str(payload.provider_id or "").strip() or None
    if not awb and not provider_id:
        raise HTTPException(status_code=422, detail="Enter an AWB or Shadowfax shipment/order ID.")
    order, operations, shipment = await _load_context(order_id, db)
    if order.cancelled_at or str(order.shopify_status or "").strip().casefold() in {"cancelled", "canceled"}:
        raise HTTPException(status_code=409, detail="Cancelled Shopify orders cannot be marked as shipped through Shadowfax.")
    existing = get_shipment(db, order_id)
    if existing and has_persisted_provider_booking_evidence(shipment_snapshot(existing)):
        raise HTTPException(status_code=409, detail="An active shipment already exists for this order.")
    if has_existing_shipment_evidence(order, operations, shipment):
        raise HTTPException(status_code=409, detail="An active shipment or fulfilment already exists for this order.")
    selected = operations.get("selected_courier")
    if not isinstance(selected, dict) or str(selected.get("provider") or "").casefold() != "shadowfax":
        raise HTTPException(status_code=400, detail="Select the manual Shadowfax courier option first.")
    actor = current_actor(request)
    booked_at = payload.booked_at or datetime.now(timezone.utc)
    service = str(payload.service_name or "").strip() or None
    saved = upsert_shipment(
        db, order_id, provider="shadowfax", provider_order_id=provider_id,
        shipment_id=provider_id, awb=awb, courier_name=service, courier_service=service,
        booking_status="booked", booking_mode="manual", booked_at=booked_at,
        latest_status="Booked manually", normalized_status="booked",
        booking_confidence="confirmed", reconciliation_status="confirmed",
        booking_freight=payload.freight, booking_operator=actor,
        booking_note=str(payload.note or "").strip() or None,
    )
    OrderOperationsStore.record_timeline_event(order_id, "shadowfax_manual_shipment_recorded", operator=actor)
    cleanup = await _cleanup_unused_shiprocket_order(order_id, order.order_number, actor)
    synchronized = await _sync_shopify_after_booking(db, order) if awb else shipment_snapshot(saved)
    return {"provider": "shadowfax", "shipment": synchronized or shipment_snapshot(saved), "shiprocket_cleanup": cleanup, "warning": cleanup.get("error")}


@booking_router.post("/shadowfax-test-324663")
async def temporary_shadowfax_direct_test_324663(
    request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db),
) -> dict[str, object]:
    """Temporary, admin-only, single-order production validation endpoint."""
    user = current_user(request)
    if user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")

    order = next(
        (item for item in await ShopifyService().get_latest_orders(force_refresh=True) if item.order_number.lstrip("#") == "324663"),
        None,
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Shopify order 324663 was not found.")
    operations = OrderOperationsStore.get(order.order_id)
    existing = get_shipment(db, order.order_id)
    existing_snapshot = shipment_snapshot(existing) if existing else None
    cancelled = bool(order.cancelled_at) or str(order.shopify_status or "").casefold() in {"cancelled", "canceled"}
    fulfilled = str(order.fulfillment_status or "unfulfilled").casefold() != "unfulfilled"
    persisted_status = str((existing_snapshot or {}).get("booking_status") or "").casefold()
    if cancelled or fulfilled:
        raise HTTPException(status_code=409, detail="Order 324663 is cancelled or fulfilled and cannot be tested.")
    if (existing_snapshot or {}).get("awb") or (existing_snapshot or {}).get("provider_order_id") or (existing_snapshot or {}).get("shipment_id") or persisted_status in {"booked", "manual_confirmed"}:
        raise HTTPException(status_code=409, detail="Order 324663 already has a provider identifier or booked shipment state.")
    if has_existing_shipment_evidence(order, operations, existing_snapshot):
        raise HTTPException(status_code=409, detail="Order 324663 already has shipment or fulfilment evidence.")
    if any(event.get("action") == "shadowfax_direct_test_324663_started" for event in operations.get("timeline_events", [])):
        raise HTTPException(status_code=409, detail="The one-time Shadowfax request for order 324663 was already attempted.")
    eligibility = ShiprocketService().evaluate_booking_eligibility(order, operations, existing_snapshot)
    if not eligibility.eligible:
        raise HTTPException(status_code=409, detail={"message": "Order 324663 is not Ready for Booking.", "missing_requirements": eligibility.missing_requirements})
    package_data = operations.get("package_details")
    if not isinstance(package_data, dict):
        raise HTTPException(status_code=409, detail="Package details are required before the Shadowfax test.")
    package = PackageDetailsPayload.model_validate(package_data)
    selected_for_context = operations.get("selected_courier") if isinstance(operations.get("selected_courier"), dict) else {"provider": "shadowfax", "courier_name": "Shadowfax Direct", "courier_id": "regular"}
    context = _booking_context(order, operations, package, selected_for_context)
    booking_request = await _build_provider_booking_request(context.order, _context_operations(context), context.package)
    delivery_pincode = str((booking_request.get("customer_details") or {}).get("pincode") or "")
    for key in ("pickup_details", "rto_details"):
        details = booking_request.get(key)
        if isinstance(details, dict):
            details.pop("unique_code", None)
            details["name"] = "Mumchies Foods"
            details["pincode"] = 560076
    _validate_shadowfax_booking_request(booking_request)
    _assert_booking_payload(context, "shadowfax", booking_request)

    adapter = ShadowfaxAdapter()
    OrderOperationsStore.update_shadowfax_direct_test(
        order.order_id, serviceability_started_at=datetime.now(timezone.utc).isoformat(), final_test_state="checking_serviceability",
    )
    try:
        serviceability = await adapter.serviceability({"delivery_pincode": delivery_pincode})
    except Exception as error:
        OrderOperationsStore.update_shadowfax_direct_test(
            order.order_id, serviceability_result={"error": str(error)[:1000]}, final_test_state="serviceability_failed",
        )
        raise
    OrderOperationsStore.update_shadowfax_direct_test(
        order.order_id,
        serviceability_result={"serviceable": serviceability.serviceable, "pincode": delivery_pincode, "service": serviceability.quotes[0].service_type if serviceability.quotes else None},
        final_test_state="serviceable" if serviceability.serviceable else "not_serviceable",
    )
    if not serviceability.serviceable:
        raise HTTPException(status_code=409, detail=f"Shadowfax does not report pincode {delivery_pincode} as serviceable.")

    actor = current_actor(request)
    OrderOperationsStore.record_timeline_event(order.order_id, "shadowfax_direct_test_324663_started", operator=actor)
    upsert_shipment(
        db, order.order_id, provider="shadowfax", provider_order_id=None,
        booking_status="booking_initiated", latest_status="Shadowfax direct test submitted",
        booking_confidence=None, reconciliation_status=None, last_synced_at=datetime.now(timezone.utc),
    )
    OrderOperationsStore.update_shadowfax_direct_test(
        order.order_id, create_request_started_at=datetime.now(timezone.utc).isoformat(),
        create_request_completed_at=None, create_http_status=None, create_result="unknown",
        sanitized_provider_error=None, final_test_state="create_request_in_flight",
    )
    observer_token = set_shadowfax_outbound_observer(
        lambda snapshot: OrderOperationsStore.update_shadowfax_direct_test(
            order.order_id, outbound_request_snapshot=snapshot,
        )
    )
    try:
        booking = await adapter.create_booking(booking_request)  # exactly one provider create POST; transport has no retries
    except Exception as error:
        uncertain = not isinstance(error, ProviderError) or error.uncertain
        message = str(error)
        result = "timeout" if "timed out" in message.casefold() else "transport_error" if uncertain else "provider_rejected"
        OrderOperationsStore.update_shadowfax_direct_test(
            order.order_id, create_request_completed_at=datetime.now(timezone.utc).isoformat(),
            create_http_status=getattr(error, "http_status", None), create_result=result,
            sanitized_provider_error=message[:1000], final_test_state="create_outcome_unknown" if uncertain else "provider_rejected",
        )
        upsert_shipment(
            db, order.order_id, booking_status="booking_uncertain" if uncertain else "booking_failed",
            latest_status="Provider response uncertain" if uncertain else "Booking failed",
            booking_confidence="uncertain", reconciliation_status="pending" if uncertain else "failed",
            reconciliation_error=str(error), last_synced_at=datetime.now(timezone.utc),
        )
        raise HTTPException(status_code=502, detail=str(error)) from error
    finally:
        reset_shadowfax_outbound_observer(observer_token)

    # The transport maps only Shadowfax `data.id` to provider_order_id/shipment_id.
    OrderOperationsStore.update_shadowfax_direct_test(
        order.order_id, create_request_completed_at=datetime.now(timezone.utc).isoformat(),
        create_http_status=(booking.raw_response or {}).get("http_status") if isinstance(booking.raw_response, dict) else 200,
        create_result="success", returned_provider_id=booking.provider_order_id,
        returned_awb=booking.awb, final_test_state="create_succeeded",
    )
    CourierPlatformService().persist_booking(db, order.order_id, booking)
    OrderOperationsStore.update_shadowfax_direct_test(
        order.order_id, persistence_completed_at=datetime.now(timezone.utc).isoformat(), final_test_state="persisted",
    )
    OrderOperationsStore.record_timeline_event(
        order.order_id, "shadowfax_direct_test_324663_booked", operator=actor,
        details={"provider_order_id": booking.provider_order_id, "shipment_id": booking.shipment_id, "awb": booking.awb},
    )
    OrderOperationsStore.record_timeline_event(
        order.order_id, "shiprocket_cleanup", operator=actor,
        details={"status": "pending", "reason": "confirmed_shadowfax_direct_booking"},
    )
    cleanup = await _cleanup_unused_shiprocket_order(order.order_id, order.order_number, actor)
    background_tasks.add_task(_run_post_booking_work, order.order_id, order.order_number, order.shopify_graphql_id, "shadowfax", actor)
    OrderOperationsStore.update_shadowfax_direct_test(
        order.order_id, tracking_started_at=datetime.now(timezone.utc).isoformat(), final_test_state="tracking_in_progress",
    )
    try:
        tracking = await CourierPlatformService().track(
            db, order_id=order.order_id, adapter=adapter, operator=actor,
        )
        tracking_summary = {
            "status": tracking.get("latest_status"), "normalized_status": tracking.get("normalized_status"),
            "latest_scan": tracking.get("latest_scan"), "tracking_url": tracking.get("tracking_url"),
        }
        OrderOperationsStore.update_shadowfax_direct_test(
            order.order_id, tracking_result=tracking_summary, final_test_state="completed",
        )
    except Exception as error:
        tracking_summary = {"error": str(error)[:1000]}
        OrderOperationsStore.update_shadowfax_direct_test(
            order.order_id, tracking_result=tracking_summary, final_test_state="tracking_failed_after_booking",
        )
        raise
    return {
        "serviceability": {"serviceable": True, "pincode": delivery_pincode, "service": serviceability.quotes[0].service_type if serviceability.quotes else None},
        "booking": {
            "provider": "shadowfax", "client_order_id": "324663",
            "provider_order_id": booking.provider_order_id, "shipment_id": booking.shipment_id,
            "awb": booking.awb, "tracking_url": booking.tracking_url,
            "status": booking.status.value, "service": booking.service,
        },
        "tracking": tracking_summary,
        "shiprocket_cleanup": cleanup,
    }


@booking_router.get("/shadowfax-test-324663/status")
async def temporary_shadowfax_direct_test_324663_status(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    user = current_user(request)
    if user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")
    order = next(
        (item for item in await ShopifyService().get_latest_orders() if item.order_number.lstrip("#") == "324663"),
        None,
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Shopify order 324663 was not found.")
    operations = OrderOperationsStore.get(order.order_id)
    state = operations.get("shadowfax_direct_test")
    if not isinstance(state, dict):
        attempted = next(
            (event for event in operations.get("timeline_events", []) if event.get("action") == "shadowfax_direct_test_324663_started"),
            None,
        )
        state = {
            "serviceability_started_at": None, "serviceability_result": None,
            "create_request_started_at": None, "create_request_completed_at": None,
            "create_http_status": None, "create_result": "unknown" if attempted else None,
            "sanitized_provider_error": None, "returned_provider_id": None, "returned_awb": None,
            "persistence_completed_at": None, "tracking_started_at": None, "tracking_result": None,
            "final_test_state": "legacy_attempt_observed_without_diagnostics" if attempted else "not_attempted",
            "one_time_guard_set_at": attempted.get("timestamp") if attempted else None,
        }
    shipment = shipment_snapshot(get_shipment(db, order.order_id))
    cancelled = bool(order.cancelled_at) or str(order.shopify_status or "").casefold() in {"cancelled", "canceled"}
    fulfilled = str(order.fulfillment_status or "unfulfilled").casefold() != "unfulfilled"
    successful_status = str(shipment.get("booking_status") or "").casefold() in {"booked", "manual_confirmed"}
    evidence = {
        "awb": shipment.get("awb") or (order.external_tracking.awb if order.external_tracking else None),
        "provider_order_id": shipment.get("provider_order_id"),
        "shipment_id": shipment.get("shipment_id"),
        "booking_status": shipment.get("booking_status"),
        "booked_at": shipment.get("booked_at"),
    }
    eligible = not cancelled and not fulfilled and not any((evidence["awb"], evidence["provider_order_id"], evidence["shipment_id"], successful_status))
    state = {
        **state, "eligible_for_test": eligible, "payment_type": order.payment_type,
        "destination_pincode": str((order.shipping_address.pincode if order.shipping_address else "") or ""),
        "shipment_evidence": evidence,
        "blocker": None if eligible else "Order is cancelled, fulfilled, or already has shipment evidence.",
    }
    return {"order_number": "324663", "state": state}


def _sanitized_persisted_provider_response(value: str | None) -> object | None:
    """Return persisted provider metadata with credential-like keys redacted."""
    if value is None:
        return None
    try:
        parsed: object = json.loads(value)
    except (TypeError, ValueError):
        return value
    return ShiprocketService.sanitize_response(parsed)


@booking_router.get("/shadowfax-test-324663/shipment-row")
async def temporary_shadowfax_direct_test_324663_shipment_row(
    request: Request, db: Session = Depends(get_db),
) -> dict[str, object]:
    """Admin-only, read-only inspection of the one canonical shipment row."""
    user = current_user(request)
    if user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")

    order = next(
        (item for item in await ShopifyService().get_latest_orders() if item.order_number.lstrip("#") == "324663"),
        None,
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Shopify order 324663 was not found.")
    shipment = get_shipment(db, order.order_id)
    values: dict[str, object | None] = {
        "provider": shipment.provider if shipment else None,
        "provider_order_id": shipment.provider_order_id if shipment else None,
        "shipment_id": shipment.shipment_id if shipment else None,
        "awb": shipment.awb if shipment else None,
        "booking_status": shipment.booking_status if shipment else None,
        "booked_at": shipment.booked_at.isoformat() if shipment and shipment.booked_at else None,
        "latest_status": shipment.latest_status if shipment else None,
        "courier_name": shipment.courier_name if shipment else None,
        "courier_service": shipment.courier_service if shipment else None,
        "raw_provider_response": _sanitized_persisted_provider_response(shipment.raw_provider_response if shipment else None),
        # The canonical shipment table currently has no created_at/updated_at columns.
        "created_at": None,
        "updated_at": None,
    }
    shadowfax_record = str(values["provider"] or "").casefold() == "shadowfax"
    successful_status = str(values["booking_status"] or "").casefold() in {"booked", "manual_confirmed"}
    stale_client_reference = (
        values["provider_order_id"] == "324663"
        and str(values["booking_status"] or "").casefold() == "booking_failed"
        and values["shipment_id"] is None and values["awb"] is None and values["booked_at"] is None
    )
    blocker_fields = [
        field for field in ("shipment_id", "awb") if values[field] is not None
    ]
    if values["provider_order_id"] is not None and not stale_client_reference:
        blocker_fields.insert(0, "provider_order_id")
    if successful_status:
        blocker_fields.append("booking_status")
    if values["booked_at"] is not None:
        blocker_fields.append("booked_at")
    blocker_true = shadowfax_record and bool(blocker_fields)
    return {
        "order_number": "324663",
        "shopify_order_id": order.order_id,
        "row_exists": shipment is not None,
        "fields": values,
        "non_null": {field: value is not None for field, value in values.items()},
        "reset_blocker": {
            "evaluates_true": blocker_true,
            "condition": "provider == shadowfax AND (genuine provider_order_id OR shipment_id OR awb OR booked_at OR booking_status in [booked, manual_confirmed])",
            "true_fields": blocker_fields if shadowfax_record else [],
        },
    }


@booking_router.post("/shadowfax-test-324541/repair-stale-state")
async def repair_temporary_shadowfax_direct_test_324541(
    request: Request, db: Session = Depends(get_db),
) -> dict[str, object]:
    """Owner/admin-triggered exact-match local repair; performs no external calls."""
    user = current_user(request)
    if user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")
    before = get_shipment(db, "6854925713486")
    exact_failed_shape = bool(
        before
        and str(before.provider or "").casefold() == "shadowfax"
        and before.provider_order_id in {None, "324541"}
        and before.shipment_id is None
        and before.awb is None
        and str(before.booking_status or "").casefold() == "booking_failed"
        and before.booked_at is None
    )
    if not exact_failed_shape:
        raise HTTPException(status_code=409, detail="The canonical row no longer matches the exact approved stale state; nothing was changed.")
    result = repair_legacy_shadowfax_test_324541(db)
    repaired = get_shipment(db, "6854925713486")
    if repaired is None or repaired.provider_order_id is not None:
        raise HTTPException(status_code=409, detail="The stale client order identifier was not cleared; nothing further was changed.")
    return {
        "order_number": "324541",
        "provider_order_id_cleared": True,
        "test_state_reset": result["test_state_reset"],
        "state": OrderOperationsStore.get("6854925713486").get("shadowfax_direct_test") or {"final_test_state": "not_attempted"},
    }


@booking_router.post("/shadowfax-test-324541/reset")
async def reset_temporary_shadowfax_direct_test_324541(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    user = current_user(request)
    if user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")
    order = next(
        (item for item in await ShopifyService().get_latest_orders() if item.order_number.lstrip("#") == "324541"),
        None,
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Shopify order 324541 was not found.")
    operations = OrderOperationsStore.get(order.order_id)
    attempted = next(
        (event for event in operations.get("timeline_events", []) if event.get("action") == "shadowfax_direct_test_324541_started"),
        None,
    )
    diagnostic = operations.get("shadowfax_direct_test")
    legacy = attempted is not None and not isinstance(diagnostic, dict)
    if not legacy:
        raise HTTPException(status_code=409, detail="Only the legacy unobserved Shadowfax test attempt can be reset.")

    shipment = shipment_snapshot(get_shipment(db, order.order_id))
    shadowfax_record = str(shipment.get("provider") or "").casefold() == "shadowfax"
    successful_status = str(shipment.get("booking_status") or "").casefold() in {"booked", "manual_confirmed"}
    stale_client_reference = (
        shipment.get("provider_order_id") == "324541"
        and str(shipment.get("booking_status") or "").casefold() == "booking_failed"
        and not shipment.get("shipment_id") and not shipment.get("awb") and not shipment.get("booked_at")
    )
    if shadowfax_record and (
        (shipment.get("provider_order_id") and not stale_client_reference)
        or shipment.get("shipment_id") or shipment.get("awb") or shipment.get("booked_at") or successful_status
    ):
        raise HTTPException(status_code=409, detail="A persisted Shadowfax booking identifier or successful booking exists; reset is blocked.")

    OrderOperationsStore.reset_legacy_shadowfax_direct_test(order.order_id)
    return {"order_number": "324541", "reset": True, "state": {"final_test_state": "not_attempted"}}


def _booking_selection_matches(selected: object, payload: BookingPayload) -> bool:
    if not isinstance(selected, dict):
        return False
    if str(selected.get("courier_id") or "") != str(payload.courier_id):
        return False
    stored_provider = str(selected.get("provider") or "shiprocket").strip().casefold()
    if payload.provider and payload.provider.strip().casefold() != stored_provider:
        return False
    stored_name = str(selected.get("courier_name") or "").strip().casefold()
    if payload.courier_name and payload.courier_name.strip().casefold() != stored_name:
        return False
    return bool(stored_provider and stored_name)


def _finish_booking_response(
    order_id: str, provider: str, result: dict[str, object], canonical: dict[str, object] | None,
    stages: dict[str, float], request_started: float, response: Response | None,
) -> dict[str, object]:
    stages["total_backend"] = (time.perf_counter() - request_started) * 1000
    if response is not None:
        response.headers["Server-Timing"] = ", ".join(f"book_{name};dur={value:.2f}" for name, value in stages.items())
    LOGGER.info(
        "book_shipment order_id=%s provider=%s %s", order_id, provider,
        " ".join(f"{name}_ms={value:.2f}" for name, value in stages.items()),
    )
    return {
        "provider": provider, **result, "shipment": canonical or result.get("shipment"),
        "post_booking_status": "pending",
    }


async def shiprocket_book_shipment(
    order_id: str, payload: BookingPayload, db: Session, operator: str = "Mumchies OS",
    *, background_tasks: BackgroundTasks | None = None, response: Response | None = None,
) -> dict[str, object]:
    actor = operator
    request_started = time.perf_counter()
    stages: dict[str, float] = {}
    try:
        stage_started = time.perf_counter()
        order = await _load_order(order_id)
        stages["fresh_shopify_integrity_get"] = (time.perf_counter() - stage_started) * 1000
        stage_started = time.perf_counter()
        operations = OrderOperationsStore.get(order_id)
        local_shipment = get_shipment(db, order_id)
        shipment = shipment_snapshot(local_shipment) if local_shipment else None
        stages["booking_context_load"] = (time.perf_counter() - stage_started) * 1000
        package = PackageDetailsPayload.model_validate(payload.model_dump())
        existing = local_shipment
        if existing and has_persisted_provider_booking_evidence(shipment_snapshot(existing)):
            return {"provider": existing.provider or "shiprocket", "existing": True, "shipment": shipment_snapshot(existing)}
        if existing and has_uncertain_provider_booking(shipment_snapshot(existing)):
            raise HTTPException(status_code=409, detail="A submitted booking request has an uncertain outcome. Reconcile it before retrying.")

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
        if not _booking_selection_matches(selected, payload):
            raise HTTPException(status_code=400, detail="Selected courier does not match the stored courier selection.")
        if payload.draft_order_id != order_id:
            raise HTTPException(status_code=409, detail="Booking blocked: package or drawer state belongs to a different order.")
        stage_started = time.perf_counter()
        context = _booking_context(order, operations, package, selected)
        if payload.address_revision != context.address_revision or payload.booking_context_hash != context.context_hash:
            raise HTTPException(status_code=409, detail="Booking blocked: order data changed or could not be verified. Reload the order before booking.")
        stages["integrity_comparison"] = (time.perf_counter() - stage_started) * 1000

        provider = str(selected.get("provider") or "shiprocket").lower()
        if payload.provider and payload.provider.lower() != provider:
            raise HTTPException(status_code=400, detail="Requested provider does not match the stored courier selection.")
        if provider == "shadowfax":
            raise HTTPException(status_code=409, detail="Shadowfax is manual-booking only. Use Mark as shipped through Shadowfax.")
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
            provider_payload = _build_delhivery_payload(context.order, _context_operations(context), context.package)
            _assert_booking_payload(context, "delhivery", provider_payload)
            stage_started = time.perf_counter()
            result = await service.book_order_shipment(
                db, order_id, order.order_number,
                provider_payload,
                context.package.model_dump(), payload.courier_id,
                str(selected.get("courier_name") or "Delhivery Surface"),
            )
            stages["provider_post_and_canonical_persistence"] = (time.perf_counter() - stage_started) * 1000
            stage_started = time.perf_counter()
            _activate_new_label_tracking(db, order_id, result)
            upsert_shipment(db, order_id, shopify_fulfillment_sync_status="pending", shopify_fulfillment_sync_error=None)
            canonical = shipment_snapshot(get_shipment(db, order_id))
            stages["canonical_readback_and_label_state"] = (time.perf_counter() - stage_started) * 1000
            if background_tasks is not None:
                OrderOperationsStore.record_timeline_event(
                    order_id, "shiprocket_cleanup", operator=actor,
                    details={"status": "pending", "reason": "confirmed_delhivery_booking"},
                )
                cleanup_started = time.perf_counter()
                cleanup = await _cleanup_unused_shiprocket_order(order_id, order.order_number, actor)
                stages["shiprocket_cleanup"] = (time.perf_counter() - cleanup_started) * 1000
                background_tasks.add_task(_run_post_booking_work, order_id, order.order_number, order.shopify_graphql_id, "delhivery", actor)
            else:
                cleanup = {"status": "not_scheduled"}
            response_result = {**result, "shiprocket_cleanup": cleanup, "warning": cleanup.get("error")}
            return _finish_booking_response(order_id, "delhivery", response_result, canonical, stages, request_started, response)

        order_payload = _build_shiprocket_order_payload(context.order, _context_operations(context), context.package)
        _assert_booking_payload(context, "shiprocket", order_payload)
        service = ShiprocketService()
        stage_started = time.perf_counter()
        result = await service.book_order_shipment(
            db,
            order_id,
            order_payload,
            courier_id=payload.courier_id,
            package_details=package.model_dump(),
            courier_name=str(selected.get("courier_name") or ""),
        )
        stages["provider_post_and_canonical_persistence"] = (time.perf_counter() - stage_started) * 1000
        stage_started = time.perf_counter()
        _activate_new_label_tracking(db, order_id, result)
        upsert_shipment(db, order_id, shopify_fulfillment_sync_status="pending", shopify_fulfillment_sync_error=None)
        canonical = shipment_snapshot(get_shipment(db, order_id))
        stages["canonical_readback_and_label_state"] = (time.perf_counter() - stage_started) * 1000
        if background_tasks is not None:
            background_tasks.add_task(_run_post_booking_work, order_id, order.order_number, order.shopify_graphql_id, "shiprocket", actor)
        return _finish_booking_response(order_id, "shiprocket", result, canonical, stages, request_started, response)
    except DelhiveryError as error:
        raise HTTPException(status_code=502, detail={"message": str(error), "upstream_status": error.status_code}) from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail={"message": "Unable to reach Delhivery. No automatic retry was attempted."}) from error
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketPersistenceError as error:
        raise HTTPException(status_code=500, detail={"message": str(error), **error.safe_details}) from error
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
async def provider_book_shipment(
    order_id: str, payload: BookingPayload, request: Request, background_tasks: BackgroundTasks,
    response: Response, db: Session = Depends(get_db),
) -> dict[str, object]:
    """Provider-neutral booking entrypoint; delegates to the existing guarded implementation."""
    return await shiprocket_book_shipment(
        order_id, payload, db, current_actor(request), background_tasks=background_tasks, response=response,
    )


@booking_router.post("/{order_id}/booking-context")
async def preview_booking_context(order_id: str, payload: BookingPreviewPayload, db: Session = Depends(get_db)) -> dict[str, object]:
    if payload.draft_order_id != order_id:
        raise HTTPException(status_code=409, detail="Booking preview belongs to a different order.")
    shopify = ShopifyService()
    order = shopify.get_cached_order(order_id) or await _load_order(order_id)
    operations = OrderOperationsStore.get(order_id)
    local_shipment = get_shipment(db, order_id)
    shipment = shipment_snapshot(local_shipment) if local_shipment else None
    if has_existing_shipment_evidence(order, operations, shipment):
        raise HTTPException(status_code=409, detail="An active shipment or fulfilment already exists for this order.")
    selected = operations.get("selected_courier")
    booking_payload = BookingPayload(**payload.model_dump(), booking_context_hash="preview")
    if not _booking_selection_matches(selected, booking_payload):
        raise HTTPException(status_code=409, detail="Selected courier does not match this order.")
    context = _booking_context(order, operations, PackageDetailsPayload.model_validate(payload.model_dump()), selected)
    if payload.address_revision != context.address_revision:
        raise HTTPException(status_code=409, detail="Address changed. Reload before booking.")
    return {
        "order_id": context.order_id, "order_number": context.order_number,
        "customer": str(context.address.get("customer_name") or context.address.get("name") or context.order.customer_name or ""),
        "city": context.address.get("city"), "pincode": context.address.get("pincode"),
        "products": [{"name": item.product_name, "quantity": item.quantity} for item in context.order.products],
        "payment": _order_payment_mode(context.order), "cod_amount": float(context.order.cod_collectable_amount),
        "courier": context.selected_courier.get("courier_name"),
        "address_revision": context.address_revision, "booking_context_hash": context.context_hash,
    }


def _shiprocket_cleanup_usage_evidence(order: dict[str, object]) -> tuple[list[str], bool]:
    """Return concrete usage evidence and whether the fresh state is ambiguous."""
    shipment_value = order.get("shipments")
    if shipment_value in (None, [], {}):
        shipments: list[dict[str, object]] = []
    elif isinstance(shipment_value, dict):
        shipments = [shipment_value]
    elif isinstance(shipment_value, list) and all(isinstance(item, dict) for item in shipment_value):
        shipments = shipment_value
    else:
        return [], True

    evidence: list[str] = []
    ambiguous = False
    known_shipment_fields = {
        "id", "order_id", "shipment_id", "status", "status_code", "created_at", "updated_at",
        "awb", "awb_code", "last_mile_awb", "rto_awb", "return_awb", "code",
        "courier", "courier_id", "sr_courier_name",
        "manifest_id", "manifest_url",
        "pickup_id", "pickup_token_number", "pickedup_timestamp", "pickup_generated_date", "pickup_scheduled_date",
        "awb_assign_date", "shipped_date", "delivered_date", "rto_initiated_date", "rto_delivered_date",
    }
    benign_static_metadata_fields = {
        # Static order/package metadata present on Shiprocket's pre-booking
        # shipment placeholder. These scalar fields do not describe carrier usage.
        "channel_id", "quantity", "weight", "volumetric_weight", "dimensions", "isd_code",
        "length", "breadth", "height", "is_single_shipment",
    }
    benign_placeholder_sentinels = {
        "cost": {"0.00"},
        "tax": {"0.00"},
        "cod_charges": {"0.00"},
        "eway_bill_number": {"-"},
    }

    def empty_placeholder_value(value: object) -> bool:
        if value in (None, "", 0, "0", False, [], {}):
            return True
        return isinstance(value, str) and value.strip().startswith("0000-00-00")

    for shipment in shipments:
        if any(str(shipment.get(key) or "").strip() for key in ("awb", "awb_code", "last_mile_awb", "rto_awb", "return_awb", "code")):
            evidence.append("awb")
        if any(str(shipment.get(key) or "").strip() for key in ("courier", "courier_id", "sr_courier_name")):
            evidence.append("courier")
        if any(str(shipment.get(key) or "").strip() for key in ("manifest_id", "manifest_url")):
            evidence.append("manifest")
        pickup_values = [shipment.get(key) for key in ("pickup_id", "pickup_token_number", "pickedup_timestamp", "pickup_generated_date")]
        scheduled = str(shipment.get("pickup_scheduled_date") or "").strip()
        if any(value not in (None, "", 0, "0") for value in pickup_values) or (scheduled and not scheduled.startswith("0000-00-00")):
            evidence.append("pickup")
        progress_dates = [str(shipment.get(key) or "").strip() for key in ("awb_assign_date", "shipped_date", "delivered_date", "rto_initiated_date", "rto_delivered_date")]
        if any(value and not value.startswith("0000-00-00") for value in progress_dates):
            evidence.append("shipment_progress")
        shipment_status = shipment.get("status")
        if not empty_placeholder_value(shipment_status):
            if isinstance(shipment_status, str) and shipment_status.strip().casefold() in {"new", "pending", "canceled", "cancelled"}:
                pass
            elif isinstance(shipment_status, str) and shipment_status.strip().casefold() in {
                "processing", "ready to ship", "pickup scheduled", "manifested", "shipped",
                "in transit", "out for delivery", "delivered", "rto", "returned",
            }:
                evidence.append("shipment_status")
            else:
                ambiguous = True
        # Fail closed on provider fields we do not understand when they carry data.
        # Empty/null additions are harmless schema noise; non-empty unknown structures
        # may represent provider processing that our explicit evidence guards do not know.
        if any(
            key not in known_shipment_fields
            and not empty_placeholder_value(value)
            and not (key in benign_static_metadata_fields and isinstance(value, (str, int, float, bool)))
            and not any(value == sentinel for sentinel in benign_placeholder_sentinels.get(key, set()))
            for key, value in shipment.items()
        ):
            ambiguous = True
    return sorted(set(evidence)), ambiguous


async def _cleanup_unused_shiprocket_order(order_id: str, channel_order_id: str, operator: str) -> dict[str, object]:
    endpoint = "https://apiv2.shiprocket.in/v1/external/orders/cancel"
    diagnostics: dict[str, object] = {
        "visible_channel_order_number": str(channel_order_id),
        "shiprocket_order_id": None,
        "fresh_shiprocket_status": None,
        "fresh_shiprocket_status_code": None,
        "shipment_id": None,
        "shipment_placeholder_present": False,
        "evidence": {
            "awb": False, "courier": False, "manifest": False,
            "pickup": False, "processing_or_progress": False,
        },
        "guards": {},
        "final_guard_decision": "lookup_not_completed",
        "request_attempted": False,
        "request_endpoint": endpoint,
        "safe_request_flags": {"cancel_on_channel": False},
        "http_status": None,
        "sanitized_shiprocket_response": None,
        "final_cleanup_classification": None,
        "fresh_post_cancellation_status": None,
        "post_cancellation_verification": "not_attempted",
    }
    try:
        service = ShiprocketService()
        matched = await service.find_existing_order(channel_order_id)
        if not matched:
            diagnostics["final_guard_decision"] = "no_matching_shiprocket_order"
            result = {"status": "not_applicable"}
        else:
            shiprocket_order_id = matched.get("id")
            diagnostics["shiprocket_order_id"] = str(shiprocket_order_id) if shiprocket_order_id is not None else None
            if shiprocket_order_id is None:
                raise ShiprocketAPIError("Shiprocket returned an ambiguous order without an ID; cleanup was blocked.")
            upstream = await service.order_details(shiprocket_order_id)
            exact_match = str(upstream.get("channel_order_id") or "").strip() == str(channel_order_id).strip()
            shipment_id, awb = service._upstream_shipment(upstream)
            status = str(upstream.get("status") or "").strip().casefold()
            usage_evidence, ambiguous = _shiprocket_cleanup_usage_evidence(upstream)
            shipment_value = upstream.get("shipments")
            evidence = {
                "awb": bool(awb or "awb" in usage_evidence),
                "courier": "courier" in usage_evidence,
                "manifest": "manifest" in usage_evidence,
                "pickup": "pickup" in usage_evidence,
                "processing_or_progress": bool({"shipment_progress", "shipment_status"}.intersection(usage_evidence)),
            }
            guards = {
                "exact_channel_match": exact_match,
                "already_cancelled": status in {"canceled", "cancelled"},
                "status_is_new": status == "new",
                "no_awb_evidence": not evidence["awb"],
                "no_courier_evidence": not evidence["courier"],
                "no_manifest_evidence": not evidence["manifest"],
                "no_pickup_evidence": not evidence["pickup"],
                "no_processing_or_progress_evidence": not evidence["processing_or_progress"],
                "provider_payload_unambiguous": not ambiguous,
            }
            diagnostics.update({
                "fresh_shiprocket_status": status,
                "fresh_shiprocket_status_code": upstream.get("status_code"),
                "shipment_id": shipment_id,
                "shipment_placeholder_present": shipment_value not in (None, [], {}),
                "evidence": evidence,
                "guards": guards,
            })
            if not exact_match:
                diagnostics["final_guard_decision"] = "blocked_channel_order_mismatch"
                result = {"status": "protected", "shiprocket_status": status, "error": "Shiprocket returned a non-matching channel order; cleanup was blocked."}
            elif status in {"canceled", "cancelled"}:
                diagnostics["final_guard_decision"] = "already_cancelled"
                diagnostics["post_cancellation_verification"] = "already_cancelled"
                ShiprocketService._new_orders_cache = None
                result = {"status": "resolved", "cancel_on_channel": False, "shiprocket_order_id": str(shiprocket_order_id), "shiprocket_status": status, "already_cancelled": True}
            elif status != "new" or awb or usage_evidence or ambiguous:
                diagnostics["final_guard_decision"] = "blocked_not_conclusively_unused_new"
                result = {"status": "protected", "awb": awb, "shipment_id": shipment_id, "shiprocket_status": status, "usage_evidence": usage_evidence, "ambiguous": ambiguous, "error": "The Shiprocket order was not cancelled because it is not conclusively an unused New order."}
            else:
                diagnostics["final_guard_decision"] = "eligible_for_cleanup"
                diagnostics["request_attempted"] = True
                cancellation = await service.cancel_unbooked_order(upstream)
                diagnostics["http_status"] = cancellation.get("http_status")
                diagnostics["sanitized_shiprocket_response"] = cancellation.get("response")
                diagnostics["final_cleanup_classification"] = cancellation.get("classification")
                if cancellation.get("classification") == "accepted":
                    ShiprocketService._new_orders_cache = None
                    result = {"status": "cancelled", "cancel_on_channel": False, "shiprocket_order_id": str(upstream.get("id"))}
                else:
                    result = {"status": "ambiguous", "cancel_on_channel": False, "error": "Shiprocket did not conclusively accept cleanup; no retry was attempted."}
                try:
                    verified = await service.order_details(shiprocket_order_id)
                    verified_status = str(verified.get("status") or "").strip().casefold()
                    diagnostics["fresh_post_cancellation_status"] = verified_status
                    diagnostics["post_cancellation_verification"] = "cancelled" if verified_status in {"canceled", "cancelled"} else f"still_{verified_status or 'unknown'}"
                except (ShiprocketAPIError, ShiprocketConfigurationError, httpx.HTTPError) as verification_error:
                    diagnostics["post_cancellation_verification"] = f"verification_failed:{type(verification_error).__name__}"
    except (ShiprocketAPIError, ShiprocketConfigurationError, httpx.HTTPError) as error:
        if isinstance(error, ShiprocketAPIError):
            safe = error.safe_details
            if diagnostics["request_attempted"] or safe.get("operation") == "cancel_order":
                diagnostics["request_attempted"] = True
                diagnostics["http_status"] = safe.get("http_status", error.status_code)
                diagnostics["sanitized_shiprocket_response"] = safe.get("response")
                diagnostics["final_cleanup_classification"] = safe.get("classification", "rejected")
        diagnostics["final_guard_decision"] = str(diagnostics["final_guard_decision"] if diagnostics["final_guard_decision"] != "lookup_not_completed" else "lookup_or_detail_failed")
        result = {"status": "failed", "cancel_on_channel": False, "error": str(error)}
    except Exception as error:  # noqa: BLE001 - persist unexpected background failures for safe retry
        LOGGER.exception("shiprocket_cleanup_unexpected_failure order_id=%s", order_id)
        diagnostics["final_guard_decision"] = "unexpected_failure"
        result = {"status": "failed", "cancel_on_channel": False, "error": f"Unexpected cleanup failure: {error}"}
    diagnostics["final_cleanup_classification"] = diagnostics["final_cleanup_classification"] or result.get("status")
    persisted = {**result, "cleanup_diagnostics": diagnostics}
    OrderOperationsStore.record_timeline_event(order_id, "shiprocket_cleanup", operator=operator, details=persisted)
    return persisted


@router.post("/shiprocket/orders/{order_id}/cleanup-unused")
async def retry_unused_shiprocket_cleanup(order_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    shipment = get_shipment(db, order_id)
    if shipment is None or shipment.provider not in {"delhivery", "shadowfax"} or not shipment.awb or shipment.booking_status != "booked":
        raise HTTPException(status_code=409, detail="Shiprocket cleanup is available only after a successful direct-provider booking with a confirmed AWB.")
    order = await _load_order(order_id)
    # Shiprocket is keyed by Shopify's channel order number. A direct-provider
    # ID is unrelated and previously made retries report not_applicable.
    return await _cleanup_unused_shiprocket_order(order_id, order.order_number, current_actor(request))


@booking_router.post("/{order_id}/courier/reconcile")
async def reconcile_provider_booking(order_id: str, payload: ProviderActionPayload, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    shipment = get_shipment(db, order_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    provider = shipment.provider or "shiprocket"
    try:
        result = await CourierPlatformService().reconcile(db, order_id=order_id, adapter=courier_registry.get(provider), operator=current_actor(request))
        return {"provider": provider, "shipment": result}
    except ProviderError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@booking_router.post("/{order_id}/courier/tracking/refresh")
async def refresh_provider_tracking(order_id: str, payload: ProviderActionPayload, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    shipment = get_shipment(db, order_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    provider = shipment.provider or "shiprocket"
    try:
        result = await CourierPlatformService().track(db, order_id=order_id, adapter=courier_registry.get(provider), operator=current_actor(request))
        return {"provider": provider, "shipment": result}
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@booking_router.post("/{order_id}/courier/cancel")
async def cancel_provider_shipment(order_id: str, payload: ProviderActionPayload, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    shipment = get_shipment(db, order_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found.")
    provider = shipment.provider or "shiprocket"
    try:
        return await CourierPlatformService().cancel(db, order_id=order_id, adapter=courier_registry.get(provider), operator=current_actor(request))
    except ProviderError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/orders/{order_id}/couriers/select")
async def select_courier(order_id: str, payload: dict[str, object], request: Request) -> dict[str, object]:
    provider = str(payload.get("provider") or "shiprocket").lower()
    courier_id = str(payload.get("courier_id") or "").strip()
    courier_name = str(payload.get("courier_name") or "").strip()
    if provider not in {"shiprocket", "delhivery", "shadowfax"} or not courier_id or not courier_name:
        raise HTTPException(status_code=422, detail="A canonical provider, courier ID and courier name are required.")
    selected = {
        "provider": provider,
        "booking_supported": provider in {"shiprocket", "delhivery", "shadowfax"} and bool(payload.get("booking_supported", True)),
        "rate_note": str(payload.get("rate_note") or ""),
        "courier_id": courier_id,
        "courier_name": courier_name,
        "rate": payload.get("rate"),
        "cod_charge": payload.get("cod_charge"),
        "total_estimated_shipping_cost": payload.get("total_estimated_shipping_cost"),
        "estimated_delivery_days": payload.get("estimated_delivery_days"),
        "expected_delivery_date": payload.get("expected_delivery_date"),
        "rating": payload.get("rating"),
        "mode": payload.get("mode"),
    }
    record = OrderOperationsStore.save_selected_courier(order_id, selected)
    OrderOperationsStore.record_timeline_event(order_id, "courier_selected", operator=current_actor(request), details={"provider": provider, "courier_id": selected["courier_id"], "courier_name": selected["courier_name"]})
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
