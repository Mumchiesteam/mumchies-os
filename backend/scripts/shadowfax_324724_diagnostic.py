"""Manually invoked, one-shot Shadowfax diagnostic for Shopify order 324724."""

from __future__ import annotations

import asyncio
import json
import shlex
from copy import deepcopy
from typing import Any

import httpx


ORDER_NUMBER = "324724"
EXPECTED_PAYMENT = "prepaid"
CONFIRMATION = "BOOK SHADOWFAX 324724 ONCE"
CREATE_PATH = "/v3/clients/orders/"


def _progress(message: str) -> None:
    print(message, flush=True)


def _sanitize(value: Any) -> Any:
    secret_keys = {"authorization", "token", "access_token", "api_key", "apikey", "password", "secret"}
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if str(key).casefold() in secret_keys else _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _json_body(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _redacted_curl(url: str, body: str) -> str:
    return " ".join((
        "curl -X POST", shlex.quote(url),
        "-H", shlex.quote("Authorization: Token [REDACTED]"),
        "-H", shlex.quote("Content-Type: application/json"),
        "--data-raw", shlex.quote(body),
    ))


async def _load_order() -> Any:
    # Import only the small Shopify service after startup output is visible. A
    # bounded name lookup replaces the full operational 15-day order retrieval.
    from app.services.shopify import ShopifyService, ShopifySyncError

    service = ShopifyService()
    fields = "id,name,status,order_number,created_at,customer,email,phone,shipping_address,line_items,shipping_lines,total_price,current_total_price,total_outstanding,financial_status,fulfillment_status,cancelled_at,tags,payment_gateway_names,fulfillments"
    url = f"https://{service.store}/admin/api/{service.api_version}/orders.json"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            url,
            params={"status": "any", "name": ORDER_NUMBER, "limit": 5, "fields": fields},
            headers=await service._admin_headers(),
        )
    response.raise_for_status()
    rows = response.json().get("orders") or []
    raw = next((row for row in rows if str(row.get("name") or row.get("order_number") or "").lstrip("#") == ORDER_NUMBER), None)
    if not isinstance(raw, dict):
        raise ShopifySyncError(f"Shopify order {ORDER_NUMBER} was not returned by the bounded name lookup.")
    return service._to_order(raw)


def _assert_preflight(order: Any, operations: dict[str, Any], shipment: dict[str, Any] | None) -> None:
    from app.services.shipment_status import has_existing_shipment_evidence

    if order.order_number.lstrip("#") != ORDER_NUMBER:
        raise RuntimeError(f"Resolved Shopify order does not match {ORDER_NUMBER}.")
    if order.cancelled_at or str(order.shopify_status or "").casefold() in {"cancelled", "canceled"}:
        raise RuntimeError(f"Order {ORDER_NUMBER} is cancelled; stopping before Shadowfax.")
    if str(order.fulfillment_status or "unfulfilled").casefold() != "unfulfilled":
        raise RuntimeError(f"Order {ORDER_NUMBER} is not unfulfilled; stopping before Shadowfax.")
    if has_existing_shipment_evidence(order, operations, shipment):
        raise RuntimeError(f"Order {ORDER_NUMBER} has existing shipment/fulfilment evidence; stopping before Shadowfax.")
    if shipment and any(shipment.get(key) for key in ("awb", "shipment_id", "provider_order_id", "booked_at")):
        raise RuntimeError(f"Order {ORDER_NUMBER} has a persisted shipment identifier; stopping before Shadowfax.")
    if str((shipment or {}).get("booking_status") or "").casefold() in {"booked", "manual_confirmed"}:
        raise RuntimeError(f"Order {ORDER_NUMBER} already has a confirmed booking state; stopping before Shadowfax.")
    if str(order.payment_type or "").casefold() != EXPECTED_PAYMENT:
        raise RuntimeError(f"Payment changed: expected {EXPECTED_PAYMENT}, got {order.payment_type!r}.")
    pincode = str(order.shipping_address.pincode if order.shipping_address else "")
    if not (pincode.isdigit() and len(pincode) == 6):
        raise RuntimeError(f"Order {ORDER_NUMBER} does not have a valid six-digit destination pincode.")
    if float(order.order_total or 0) <= 0:
        raise RuntimeError(f"Order {ORDER_NUMBER} does not have a valid positive total.")


async def _build_payload(order: Any, operations: dict[str, Any]) -> dict[str, Any]:
    from app.services.shiprocket import ShiprocketService

    address = operations.get("corrected_address") or operations.get("verified_address_snapshot") or (order.shipping_address.model_dump() if order.shipping_address else None)
    package = operations.get("package_details")
    if not isinstance(address, dict):
        raise RuntimeError("Latest operational address is missing.")
    if not isinstance(package, dict):
        raise RuntimeError("Canonical package details are missing.")
    weight = float(package.get("weight_kg") or 0)
    length = float(package.get("length_cm") or 0)
    breadth = float(package.get("breadth_cm") or 0)
    height = float(package.get("height_cm") or 0)
    if min(weight, length, breadth, height) <= 0:
        raise RuntimeError("Canonical package weight and dimensions must be greater than zero.")

    phone = str(address.get("phone") or order.phone or "").strip()
    pincode = str(address.get("pincode") or "").strip()
    customer_name = str(address.get("customer_name") or address.get("name") or order.customer_name or "").strip()
    if not phone or not customer_name or not (pincode.isdigit() and len(pincode) == 6):
        raise RuntimeError("Customer name, phone, and six-digit pincode are required.")
    required_address = {"address_line_1": address.get("address_line1") or address.get("address"), "city": address.get("city"), "state": address.get("state")}
    missing_address = [key for key, value in required_address.items() if not str(value or "").strip()]
    if missing_address:
        raise RuntimeError(f"Shipping address is missing: {', '.join(missing_address)}.")

    warehouse = await ShiprocketService().pickup_location_details()
    if not isinstance(warehouse, dict):
        raise RuntimeError("Configured Mumchies pickup details could not be resolved.")
    def warehouse_value(*keys: str) -> str:
        return str(next((warehouse.get(key) for key in keys if warehouse.get(key) not in (None, "")), "")).strip()
    warehouse_pincode = warehouse_value("postal_code", "pincode", "pin_code")
    warehouse_details = {
        "name": warehouse_value("name", "pickup_location"), "contact": warehouse_value("phone", "contact", "mobile"),
        "address_line_1": warehouse_value("address", "address_1", "address_line_1"),
        "address_line_2": warehouse_value("address_2", "address_line_2"), "city": warehouse_value("city"),
        "state": warehouse_value("state"), "pincode": int(warehouse_pincode) if warehouse_pincode.isdigit() and len(warehouse_pincode) == 6 else None,
    }
    products = []
    for item in order.products:
        product: dict[str, Any] = {"sku_name": item.product_name, "price": float(item.price), "additional_details": {"quantity": item.quantity}}
        if item.sku:
            product["sku_id"] = item.sku
        products.append(product)
    product_value = sum(float(item.price) * item.quantity for item in order.products)
    return {
        "order_type": "warehouse",
        "order_details": {
            "client_order_id": order.order_number, "client_name": "Mumchies Foods",
            "actual_weight": max(round(weight * 1000), 1),
            "volumetric_weight": max(round((length * breadth * height) / 5000 * 1000), 1),
            "product_value": product_value, "payment_mode": "Prepaid", "cod_amount": 0,
            "total_amount": float(order.order_total), "order_service": "regular",
        },
        "customer_details": {
            "name": customer_name, "contact": phone, "address_line_1": required_address["address_line_1"],
            "address_line_2": " ".join(filter(None, [address.get("address_line2"), address.get("landmark")])),
            "city": required_address["city"], "state": required_address["state"], "pincode": int(pincode),
        },
        "pickup_details": dict(warehouse_details), "rto_details": dict(warehouse_details), "product_details": products,
    }


def _validate_payload(payload: dict[str, Any]) -> None:
    order = payload.get("order_details") or {}
    if payload.get("order_type") != "warehouse":
        raise RuntimeError("order_type must be warehouse.")
    for field in ("client_order_id", "client_name", "actual_weight", "volumetric_weight", "product_value", "payment_mode", "cod_amount", "total_amount", "order_service"):
        if order.get(field) in (None, ""):
            raise RuntimeError(f"order_details.{field} is required.")
    if order.get("client_name") != "Mumchies Foods" or order.get("payment_mode") != "Prepaid" or order.get("cod_amount") != 0:
        raise RuntimeError("Shadowfax merchant/payment mapping is invalid.")
    if "client_id" in payload or "client_id" in order:
        raise RuntimeError("The payload must not invent a client_id field.")
    for label in ("customer_details", "pickup_details", "rto_details"):
        details = payload.get(label) or {}
        for field in ("name", "contact", "address_line_1", "city", "state", "pincode"):
            if details.get(field) in (None, ""):
                raise RuntimeError(f"{label}.{field} is required.")
    products = payload.get("product_details") or []
    if not products:
        raise RuntimeError("product_details is required.")
    for index, product in enumerate(products):
        if not product.get("sku_name") or product.get("price") is None or int((product.get("additional_details") or {}).get("quantity") or 0) <= 0:
            raise RuntimeError(f"product_details[{index}] is invalid.")


async def main() -> None:
    _progress("Shadowfax diagnostic starting...")
    _progress("Loading configuration...")
    from app.core.config import settings
    from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport
    from app.api.routes.couriers import PackageDetailsPayload, _assert_booking_payload, _booking_context
    token = str(settings.shadowfax_effective_token or "").strip()
    base_url = str(settings.shadowfax_base_url or "").rstrip("/")
    if not token or not base_url:
        raise RuntimeError("SHADOWFAX_API_TOKEN (or legacy SHADOWFAX_TOKEN) and SHADOWFAX_BASE_URL must be configured.")
    _progress("Configuration loaded.")

    _progress(f"Loading order {ORDER_NUMBER}...")
    order = await _load_order()
    from app.db.session import SessionLocal
    from app.repositories.shiprocket import get_shipment, snapshot as shipment_snapshot
    from app.services.order_operations import OrderOperationsStore
    operations = OrderOperationsStore.get(order.order_id)
    with SessionLocal() as db:
        stored = get_shipment(db, order.order_id)
        shipment = shipment_snapshot(stored) if stored else None
    _assert_preflight(order, operations, shipment)
    _progress(f"Order {ORDER_NUMBER} loaded and preflight passed.")
    _progress(f"Payment type: {order.payment_type}")
    _progress(f"Destination pincode: {order.shipping_address.pincode}")
    _progress(f"Order total: {float(order.order_total):.2f}")
    if not isinstance(operations.get("package_details"), dict) or not operations.get("package_details"):
        _progress("Package details missing in OS. Save package weight/dimensions for order 324724 first.")
        return

    _progress("Building payload...")
    payload = deepcopy(await _build_payload(order, operations))
    integrity_context = _booking_context(
        order, operations, PackageDetailsPayload.model_validate(operations["package_details"]),
        {"provider": "shadowfax", "courier_id": "regular", "courier_name": "Shadowfax Direct", "booking_supported": True},
    )
    _assert_booking_payload(integrity_context, "shadowfax", payload)
    _progress("Payload built.")
    _progress("Validating payload...")
    _validate_payload(payload)
    _progress("Payload validation passed.")

    url = f"{base_url}{CREATE_PATH}"
    body = _json_body(payload)
    _progress("Displaying payload/cURL...")
    print("METHOD: POST")
    print(f"FINAL URL: {url}")
    print("HEADER NAMES: Authorization, Content-Type")
    print("AUTHORIZATION: Token [REDACTED]")
    print(f"order_details.client_name: {payload['order_details']['client_name']}")
    print("FINAL JSON (exact request bytes):")
    print(body)
    print("REDACTED CURL:")
    print(_redacted_curl(url, body), flush=True)
    _progress("Payload/cURL displayed.")
    entered = input(f'Type "{CONFIRMATION}" to continue: ').strip()
    if entered != CONFIRMATION:
        _progress("ABORTED: confirmation did not match. No Shadowfax request was made.")
        return

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False) as client:
        transport = ShadowfaxHTTPTransport(token=token, base_url=base_url, client=client)
        serviceability = await transport.serviceability({"delivery_pincode": str(payload["customer_details"]["pincode"])})
        print("SERVICEABILITY:")
        print(json.dumps(_sanitize(serviceability), ensure_ascii=False, separators=(",", ":"), default=str))
        if not serviceability.get("serviceable"):
            _progress("STOPPED: destination is not serviceable. No create-order request was made.")
            return
        try:  # Exactly one POST; deliberately no retry branch.
            response = await client.post(url, headers={"Authorization": f"Token {token}", "Content-Type": "application/json"}, content=body.encode("utf-8"), timeout=httpx.Timeout(20.0, connect=10.0))
        except (httpx.TimeoutException, httpx.TransportError) as error:
            _progress(f"CREATE RESULT: AMBIGUOUS TRANSPORT FAILURE ({type(error).__name__}). NO RETRY.")
            return
        print(f"CREATE HTTP STATUS: {response.status_code}")
        try:
            provider_body: Any = response.json()
        except ValueError:
            provider_body = {"non_json_body": response.text}
        print("CREATE RESPONSE:")
        print(json.dumps(_sanitize(provider_body), ensure_ascii=False, separators=(",", ":"), default=str))
        data = provider_body.get("data") if isinstance(provider_body, dict) and isinstance(provider_body.get("data"), dict) else {}
        if not (response.is_success and isinstance(provider_body, dict) and str(provider_body.get("message") or "").casefold() == "success"):
            _progress("CREATE RESULT: PROVIDER REJECTED. NO RETRY.")
            return
        provider_id, awb = str(data.get("id") or ""), str(data.get("awb_number") or "")
        print(f"PROVIDER ID: {provider_id or '[MISSING]'}")
        print(f"AWB: {awb or '[MISSING]'}")
        if not awb:
            _progress("TRACKING: SKIPPED; successful response did not contain an AWB.")
            return
        tracking = await transport.track_shipment({"awb": awb})
        print("TRACKING RESPONSE:")
        print(json.dumps(_sanitize(tracking), ensure_ascii=False, separators=(",", ":"), default=str))


if __name__ == "__main__":
    asyncio.run(main())
