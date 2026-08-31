"""Interactive, manually invoked Shadowfax batch preflight and one-POST-at-a-time booking tool."""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass
from typing import Any

import httpx


ORDER_NUMBERS = ("324823", "324827", "324826", "324825", "324824")
CREATE_PATH = "/v3/clients/orders/"


@dataclass
class Preflight:
    number: str
    payment: str = "?"
    amount: float = 0
    pincode: str = "?"
    package_ok: bool = False
    serviceable: bool = False
    existing: bool = False
    ready: bool = False
    service: str = "-"
    payload: dict[str, Any] | None = None
    error: str | None = None


def _redacted_curl(base_url: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return " ".join(("curl -X POST", shlex.quote(f"{base_url}{CREATE_PATH}"), "-H", shlex.quote("Authorization: Token [REDACTED]"), "-H", shlex.quote("Content-Type: application/json"), "--data-raw", shlex.quote(body)))


async def _load_orders() -> dict[str, Any]:
    from app.services.shopify import ShopifyService

    service = ShopifyService()
    fields = "id,name,status,order_number,created_at,customer,email,phone,shipping_address,line_items,shipping_lines,total_price,current_total_price,total_outstanding,financial_status,fulfillment_status,cancelled_at,tags,payment_gateway_names,fulfillments"
    url = f"https://{service.store}/admin/api/{service.api_version}/orders.json"
    found: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        for number in ORDER_NUMBERS:
            response = await client.get(url, params={"status": "any", "name": number, "limit": 5, "fields": fields}, headers=await service._admin_headers())
            response.raise_for_status()
            raw = next((row for row in response.json().get("orders", []) if str(row.get("name") or row.get("order_number") or "").lstrip("#") == number), None)
            if isinstance(raw, dict):
                found[number] = service._to_order(raw)
    return found


def _validate_payload(payload: dict[str, Any]) -> None:
    order = payload.get("order_details") or {}
    if payload.get("order_type") != "warehouse" or order.get("client_name") != "Mumchies Foods":
        raise RuntimeError("Invalid Shadowfax warehouse/client mapping.")
    if "client_id" in payload or "client_id" in order or "unique_code" in payload:
        raise RuntimeError("Payload contains a prohibited invented identifier.")
    for section in ("pickup_details", "rto_details"):
        if "unique_code" in (payload.get(section) or {}):
            raise RuntimeError(f"{section}.unique_code is prohibited.")
    for field in ("client_order_id", "client_name", "actual_weight", "volumetric_weight", "product_value", "payment_mode", "cod_amount", "total_amount", "order_service"):
        if order.get(field) in (None, ""):
            raise RuntimeError(f"order_details.{field} is required.")
    for section in ("customer_details", "pickup_details", "rto_details"):
        details = payload.get(section) or {}
        for field in ("name", "contact", "address_line_1", "city", "state", "pincode"):
            if details.get(field) in (None, ""):
                raise RuntimeError(f"{section}.{field} is required.")
    products = payload.get("product_details") or []
    if not products or any(not item.get("sku_name") or item.get("price") is None or int((item.get("additional_details") or {}).get("quantity") or 0) <= 0 for item in products):
        raise RuntimeError("product_details is missing or invalid.")
    payment, cod = str(order.get("payment_mode")), float(order.get("cod_amount") or 0)
    if payment not in {"COD", "Prepaid"} or (payment == "COD" and cod <= 0) or (payment == "Prepaid" and cod != 0):
        raise RuntimeError("Payment/COD mapping is invalid.")


async def _preflight(number: str, order: Any | None, transport: Any) -> Preflight:
    from app.api.routes.couriers import PackageDetailsPayload, _assert_booking_payload, _booking_context, _build_provider_booking_request, _context_operations, _order_payment_mode
    from app.db.session import SessionLocal
    from app.repositories.shiprocket import get_shipment, snapshot
    from app.services.order_operations import OrderOperationsStore
    from app.services.shipment_status import has_existing_shipment_evidence

    result = Preflight(number=number)
    try:
        if order is None:
            raise RuntimeError("Shopify order not found.")
        operations = OrderOperationsStore.get(order.order_id)
        with SessionLocal() as db:
            stored = get_shipment(db, order.order_id)
            shipment = snapshot(stored) if stored else None
        result.payment = _order_payment_mode(order)
        result.amount = float(order.cod_collectable_amount) if result.payment == "COD" else float(order.order_total)
        address = operations.get("corrected_address") or operations.get("verified_address_snapshot") or (order.shipping_address.model_dump() if order.shipping_address else {})
        result.pincode = str((address or {}).get("pincode") or "?")
        result.existing = has_existing_shipment_evidence(order, operations, shipment) or bool(shipment and any(shipment.get(key) for key in ("awb", "shipment_id", "provider_order_id", "booked_at")))
        if order.cancelled_at or str(order.shopify_status or "").casefold() in {"cancelled", "canceled"}:
            raise RuntimeError("cancelled")
        if str(order.fulfillment_status or "unfulfilled").casefold() != "unfulfilled":
            raise RuntimeError("not unfulfilled")
        if result.existing:
            raise RuntimeError("existing shipment evidence")
        package = PackageDetailsPayload.model_validate(operations.get("package_details") or {})
        result.package_ok = True
        selected = {"provider": "shadowfax", "courier_id": "regular", "courier_name": "Shadowfax Direct", "booking_supported": True}
        context = _booking_context(order, operations, package, selected)
        payload = await _build_provider_booking_request(context.order, _context_operations(context), context.package)
        _validate_payload(payload)
        _assert_booking_payload(context, "shadowfax", payload)
        serviceability = await transport.serviceability({"delivery_pincode": result.pincode})
        result.serviceable = bool(serviceability.get("serviceable"))
        result.service = str(serviceability.get("service_type") or serviceability.get("service_id") or "-")
        result.payload = payload
        result.ready = result.package_ok and result.serviceable and not result.existing
        if not result.ready:
            result.error = str(serviceability.get("reason") or "not ready")
    except Exception as error:
        result.error = str(error)
    return result


def _print_table(rows: list[Preflight]) -> None:
    headings = ("Order", "Payment", "Amount", "Pincode", "Package OK", "Serviceable", "Existing Shipment", "Ready")
    values = [headings] + [
        (row.number, row.payment, f"{row.amount:.2f}", row.pincode, "YES" if row.package_ok else "NO", "YES" if row.serviceable else "NO", "YES" if row.existing else "NO", "YES" if row.ready else "NO")
        for row in rows
    ]
    widths = [max(len(str(row[index])) for row in values) for index in range(len(headings))]
    for index, row in enumerate(values):
        print(" | ".join(str(value).ljust(widths[column]) for column, value in enumerate(row)))
        if index == 0:
            print("-+-".join("-" * width for width in widths))
    for row in rows:
        if row.error:
            print(f"{row.number}: {row.error}")


async def run(*, input_fn=input) -> int:
    from app.core.config import settings
    from app.services.courier_platform.base import ProviderError
    from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport

    token = str(settings.shadowfax_effective_token or "").strip()
    base_url = str(settings.shadowfax_base_url or "").rstrip("/")
    fingerprint = f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "[TOO SHORT]"
    print(f"token present: {'yes' if token else 'no'}")
    print(f"token fingerprint: {fingerprint}")
    print(f"token length: {len(token)}")
    print("Authorization scheme = Token")
    if not token.strip() or not base_url:
        print("SHADOWFAX_API_TOKEN (or legacy SHADOWFAX_TOKEN) and SHADOWFAX_BASE_URL must be configured.")
        return 2
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False) as client:
        # Use the same direct transport as the proven single-order diagnostic.
        # It applies Authorization: Token <effective Shadowfax token> to every GET and POST.
        transport = ShadowfaxHTTPTransport(token=token, base_url=base_url, client=client)
        orders = await _load_orders()
        rows = [await _preflight(number, orders.get(number), transport) for number in ORDER_NUMBERS]
        _print_table(rows)
        ready = [row for row in rows if row.ready and row.payload]
        if not ready:
            print("No READY orders. No create request was made.")
            return 0

        for index, row in enumerate(ready):
            if index == 0:
                print("FINAL PAYLOAD:")
                print(json.dumps(row.payload, ensure_ascii=False, indent=2))
                print("REDACTED CURL:")
                print(_redacted_curl(base_url, row.payload))
            else:
                print(f"NEXT READY: {row.number} | {row.payment} | {row.pincode} | {row.service}")
            confirmation = f"BOOK SHADOWFAX {row.number} ONCE"
            if input_fn(f'Type "{confirmation}" to send exactly one create POST: ').strip() != confirmation:
                print("STOPPED: confirmation did not match. No request was made for this order.")
                return 0
            try:
                booking = await transport.create_booking(row.payload)  # Exactly one POST; no retry path.
            except ProviderError as error:
                print(f"STOPPED: create failed/rejected/ambiguous: {error}. NO RETRY.")
                return 1
            except (httpx.TimeoutException, httpx.TransportError) as error:
                print(f"STOPPED: ambiguous {type(error).__name__}. NO RETRY.")
                return 1
            awb = str(booking.get("awb") or "")
            provider_id = str(booking.get("provider_order_id") or booking.get("shipment_id") or "")
            if not awb or not provider_id:
                print("STOPPED: create result is ambiguous (missing provider ID or AWB). NO RETRY.")
                return 1
            print(f"SUCCESS {row.number}: provider_id={provider_id} awb={awb}")
            try:
                tracking = await transport.track_shipment({"awb": awb})
                print(f"TRACKING GET: {tracking.get('status') or 'unknown'}")
            except Exception as error:
                print(f"STOPPED: post-create tracking GET failed: {error}. Booking was not retried.")
                return 1
    print("BATCH COMPLETE: all confirmed READY orders were created once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
