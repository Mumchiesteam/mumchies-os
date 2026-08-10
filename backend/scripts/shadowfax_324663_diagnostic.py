"""One-shot, manually invoked Shadowfax diagnostic for Shopify order 324663.

This script is intentionally not imported by the application. It performs no OS or
Shopify writes and has no retry path. Run it only from an authenticated Render Shell.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from copy import deepcopy
from typing import Any

import httpx

from app.api.routes.couriers import (
    PackageDetailsPayload,
    _build_provider_booking_request,
    _validate_shadowfax_booking_request,
)
from app.core.config import settings
from app.db.session import SessionLocal
from app.repositories.shiprocket import get_shipment, snapshot as shipment_snapshot
from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport
from app.services.order_operations import OrderOperationsStore
from app.services.shipment_status import has_existing_shipment_evidence
from app.services.shopify import ShopifyService


ORDER_NUMBER = "324663"
EXPECTED_PAYMENT = "prepaid"
EXPECTED_TOTAL = 461.0
EXPECTED_PINCODE = "492001"
CONFIRMATION = "BOOK SHADOWFAX 324663 ONCE"
CREATE_PATH = "/v3/clients/orders/"


def _sanitize(value: Any) -> Any:
    secret_keys = {"authorization", "token", "access_token", "api_key", "apikey", "password", "secret"}
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).casefold() in secret_keys else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _json_body(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _redacted_curl(url: str, body: str) -> str:
    return " ".join((
        "curl -X POST",
        shlex.quote(url),
        "-H", shlex.quote("Authorization: Token [REDACTED]"),
        "-H", shlex.quote("Content-Type: application/json"),
        "--data-raw", shlex.quote(body),
    ))


def _assert_preflight(order: Any, operations: dict[str, Any], shipment: dict[str, Any] | None) -> None:
    if order.order_number.lstrip("#") != ORDER_NUMBER:
        raise RuntimeError("Resolved Shopify order does not match 324663.")
    if order.cancelled_at or str(order.shopify_status or "").casefold() in {"cancelled", "canceled"}:
        raise RuntimeError("Order 324663 is cancelled; stopping before Shadowfax.")
    if str(order.fulfillment_status or "unfulfilled").casefold() != "unfulfilled":
        raise RuntimeError("Order 324663 is not unfulfilled; stopping before Shadowfax.")
    if has_existing_shipment_evidence(order, operations, shipment):
        raise RuntimeError("Order 324663 has existing shipment/fulfilment evidence; stopping before Shadowfax.")
    if shipment and any(shipment.get(key) for key in ("awb", "shipment_id", "provider_order_id", "booked_at")):
        raise RuntimeError("Order 324663 has a persisted shipment identifier; stopping before Shadowfax.")
    if str((shipment or {}).get("booking_status") or "").casefold() in {"booked", "manual_confirmed"}:
        raise RuntimeError("Order 324663 already has a confirmed booking state; stopping before Shadowfax.")
    if str(order.payment_type or "").casefold() != EXPECTED_PAYMENT:
        raise RuntimeError(f"Payment changed: expected {EXPECTED_PAYMENT}, got {order.payment_type!r}.")
    if abs(float(order.order_total) - EXPECTED_TOTAL) > 0.001:
        raise RuntimeError(f"Order total changed: expected {EXPECTED_TOTAL}, got {order.order_total!r}.")
    pincode = str(order.shipping_address.pincode if order.shipping_address else "")
    if pincode != EXPECTED_PINCODE:
        raise RuntimeError(f"Destination changed: expected {EXPECTED_PINCODE}, got {pincode!r}.")


async def _load_payload() -> tuple[dict[str, Any], str]:
    recent = await ShopifyService().get_latest_orders(force_refresh=True)
    match = next((order for order in recent if order.order_number.lstrip("#") == ORDER_NUMBER), None)
    if match is None:
        raise RuntimeError("Shopify order 324663 was not found in the operational order window.")
    order = await ShopifyService().get_order(match.order_id)
    operations = OrderOperationsStore.get(order.order_id)
    with SessionLocal() as db:
        stored = get_shipment(db, order.order_id)
        shipment = shipment_snapshot(stored) if stored else None
    _assert_preflight(order, operations, shipment)
    package_data = operations.get("package_details")
    if not isinstance(package_data, dict):
        raise RuntimeError("Canonical package details are missing.")
    package = PackageDetailsPayload.model_validate(package_data)
    payload = await _build_provider_booking_request(order, operations, package)
    _validate_shadowfax_booking_request(payload)
    if (payload.get("order_details") or {}).get("client_name") != "Mumchies Foods":
        raise RuntimeError("order_details.client_name is not Mumchies Foods.")
    if "client_id" in payload or "client_id" in (payload.get("order_details") or {}):
        raise RuntimeError("The payload must not invent a client_id field.")
    return deepcopy(payload), order.order_id


async def main() -> None:
    token = str(settings.shadowfax_token or "").strip()
    base_url = str(settings.shadowfax_base_url or "").rstrip("/")
    if not token or not base_url:
        raise RuntimeError("SHADOWFAX_TOKEN and SHADOWFAX_BASE_URL must be configured.")

    payload, _order_id = await _load_payload()
    url = f"{base_url}{CREATE_PATH}"
    body = _json_body(payload)
    print("VALIDATION: PASSED")
    print("METHOD: POST")
    print(f"FINAL URL: {url}")
    print("HEADER NAMES: Authorization, Content-Type")
    print("AUTHORIZATION: Token [REDACTED]")
    print(f"order_details.client_name: {payload['order_details']['client_name']}")
    print("FINAL JSON (exact request bytes):")
    print(body)
    print("REDACTED CURL:")
    print(_redacted_curl(url, body))
    entered = input(f'Type "{CONFIRMATION}" to continue: ').strip()
    if entered != CONFIRMATION:
        print("ABORTED: confirmation did not match. No Shadowfax request was made.")
        return

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False) as client:
        transport = ShadowfaxHTTPTransport(token=token, base_url=base_url, client=client)
        serviceability = await transport.serviceability({"delivery_pincode": EXPECTED_PINCODE})
        print("SERVICEABILITY:")
        print(json.dumps(_sanitize(serviceability), ensure_ascii=False, separators=(",", ":"), default=str))
        if not serviceability.get("serviceable"):
            print("STOPPED: destination is not serviceable. No create-order request was made.")
            return

        # Exactly one create POST. There is deliberately no loop or retry branch.
        try:
            response = await client.post(
                url,
                headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
                content=body.encode("utf-8"),
                timeout=httpx.Timeout(20.0, connect=10.0),
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            print(f"CREATE RESULT: AMBIGUOUS TRANSPORT FAILURE ({type(error).__name__}). NO RETRY.")
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
            print("CREATE RESULT: PROVIDER REJECTED. NO RETRY.")
            return
        provider_id = str(data.get("id") or "")
        awb = str(data.get("awb_number") or "")
        print(f"PROVIDER ID: {provider_id or '[MISSING]'}")
        print(f"AWB: {awb or '[MISSING]'}")
        if not awb:
            print("TRACKING: SKIPPED; successful response did not contain an AWB.")
            return
        tracking = await transport.track_shipment({"awb": awb})
        print("TRACKING RESPONSE:")
        print(json.dumps(_sanitize(tracking), ensure_ascii=False, separators=(",", ":"), default=str))


if __name__ == "__main__":
    asyncio.run(main())
