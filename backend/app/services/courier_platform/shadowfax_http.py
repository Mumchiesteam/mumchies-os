from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.services.courier_platform.base import ProviderConfigurationError, ProviderError


class ShadowfaxHTTPTransport:
    """HTTP transport defined by the official Shadowfax Unified API Blueprint.

    The deployment-selected API base URL is accepted only over HTTPS.
    """

    def __init__(
        self,
        *,
        token: str,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme != "https" or not parsed.hostname:
            raise ProviderConfigurationError(
                "SHADOWFAX_BASE_URL must be a valid HTTPS URL.",
                provider="shadowfax",
                operation="configuration",
            )
        if not token.strip():
            raise ProviderConfigurationError(
                "SHADOWFAX_TOKEN is not configured.", provider="shadowfax", operation="configuration"
            )
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Token {token.strip()}", "Content-Type": "application/json"}
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))

    async def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                       json: dict[str, Any] | None = None) -> httpx.Response:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        try:
            response = await client.request(
                method, f"{self._base_url}{path}", headers=self._headers, params=params, json=json,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as error:
            raise ProviderError(
                "Shadowfax request timed out. No automatic retry was attempted.",
                provider="shadowfax", operation=method.casefold(), uncertain=method.upper() == "POST",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderError(
                "Shadowfax could not be reached. No automatic retry was attempted.",
                provider="shadowfax", operation=method.casefold(), uncertain=method.upper() == "POST",
            ) from error
        finally:
            if owns_client:
                await client.aclose()
        return response

    @staticmethod
    def _json(response: httpx.Response, operation: str) -> Any:
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError(
                "Shadowfax returned a non-JSON response.", provider="shadowfax", operation=operation
            ) from error
        if response.status_code >= 400:
            message = payload.get("message") or payload.get("responseMsg") or payload.get("detail") if isinstance(payload, dict) else None
            raise ProviderError(
                str(message or f"Shadowfax rejected the request with HTTP {response.status_code}."),
                provider="shadowfax", operation=operation, http_status=response.status_code,
            )
        return payload

    async def authenticate(self) -> bool:
        response = await self._request(
            "GET", "/v1/clients/serviceability/",
            params={"service": "customer_delivery", "page": 1, "count": 1, "pincodes": "560077"},
        )
        payload = self._json(response, "authenticate")
        return response.status_code == 200 and isinstance(payload, list)

    async def serviceability(self, request: dict[str, Any]) -> dict[str, Any]:
        pincode = str(request.get("delivery_pincode") or "").strip()
        if not (pincode.isdigit() and len(pincode) == 6):
            raise ProviderError("A valid six-digit delivery pincode is required.", provider="shadowfax", operation="serviceability")
        response = await self._request(
            "GET", "/v1/clients/serviceability/",
            params={"service": "customer_delivery", "page": 1, "count": 1, "pincodes": pincode},
        )
        payload = self._json(response, "serviceability")
        records = payload if isinstance(payload, list) else []
        match = next((item for item in records if isinstance(item, dict) and str(item.get("code")) == pincode), None)
        services = match.get("services") if isinstance(match, dict) and isinstance(match.get("services"), list) else []
        return {
            "serviceable": bool(match),
            "service_id": str(services[0]) if services else "shadowfax-direct",
            "courier_name": "Shadowfax Direct",
            "service_type": str(services[0]) if services else None,
            "reason": None if match else "Shadowfax does not list this pincode for customer delivery.",
            "provider_response": payload,
            "http_status": response.status_code,
        }

    @staticmethod
    def _validate_booking_payload(request: dict[str, Any]) -> None:
        required = ("order_type", "order_details", "customer_details", "pickup_details", "product_details")
        missing = [field for field in required if not request.get(field)]
        order_type = request.get("order_type")
        return_field = "rts_details" if order_type == "marketplace" else "rto_details"
        if not request.get(return_field):
            missing.append(return_field)
        if order_type not in {"marketplace", "warehouse"}:
            missing.append("order_type=marketplace|warehouse")
        if missing:
            raise ProviderError(
                f"Shadowfax booking payload is missing official required fields: {', '.join(missing)}.",
                provider="shadowfax", operation="booking",
            )

    async def create_booking(self, request: dict[str, Any]) -> dict[str, Any]:
        self._validate_booking_payload(request)
        response = await self._request("POST", "/v3/clients/orders/", json=request)
        payload = self._json(response, "booking")
        if not isinstance(payload, dict):
            raise ProviderError("Shadowfax returned an invalid booking response.", provider="shadowfax", operation="booking", uncertain=True)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if str(payload.get("message") or "").casefold() != "success":
            # The documented duplicate response is HTTP 200 and exposes its AWB
            # at the top level. Preserve it for guarded recovery.
            duplicate_awb = payload.get("AWB")
            if duplicate_awb:
                return {
                    "provider_order_id": str(payload.get("COID") or "") or None,
                    "shipment_id": str(duplicate_awb), "awb": str(duplicate_awb),
                    "status": "new", "provider_response": payload, "http_status": response.status_code,
                }
            raise ProviderError(
                str(payload.get("errors") or payload.get("message") or "Shadowfax rejected the booking."),
                provider="shadowfax", operation="booking", http_status=response.status_code,
            )
        awb = str(data.get("awb_number") or "") or None
        return {
            "provider_order_id": str(data.get("client_order_id") or "") or None,
            "shipment_id": str(data.get("id") or "") or None,
            "awb": awb,
            "status": str(data.get("status") or "new"),
            "tracking_url": str(data.get("customer_track_url") or "") or None,
            "service": str((data.get("order_details") or {}).get("order_service") or "") or None,
            "provider_response": payload,
            "http_status": response.status_code,
        }

    async def find_booking(self, merchant_order_id: str) -> dict[str, Any] | None:
        raise ProviderConfigurationError(
            "The official Shadowfax specification does not document lookup by client_order_id. Reconcile using a known AWB.",
            provider="shadowfax", operation="reconciliation",
        )

    async def track_shipment(self, shipment: dict[str, Any]) -> dict[str, Any]:
        awb = str(shipment.get("awb") or "").strip()
        if not awb:
            raise ProviderError("Shadowfax tracking requires an AWB.", provider="shadowfax", operation="tracking")
        response = await self._request("GET", f"/v4/clients/orders/{awb}/track/")
        payload = self._json(response, "tracking")
        if not isinstance(payload, dict) or not isinstance(payload.get("order_details"), dict):
            raise ProviderError("Shadowfax returned an invalid tracking response.", provider="shadowfax", operation="tracking")
        order = payload["order_details"]
        events = payload.get("tracking_details") if isinstance(payload.get("tracking_details"), list) else []
        latest = events[-1] if events and isinstance(events[-1], dict) else {}
        timestamp = latest.get("created")
        parsed_timestamp = None
        if timestamp:
            try: parsed_timestamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            except ValueError: parsed_timestamp = None
        return {
            "status": str(order.get("status") or latest.get("status_id") or ""),
            "latest_scan": str(latest.get("location") or "") or None,
            "timestamp": parsed_timestamp,
            "tracking_url": str(order.get("customer_track_url") or "") or None,
            "remarks": str(latest.get("remarks") or "") or None,
            "provider_response": payload,
        }

    async def list_ndr_shipments(self) -> list[dict[str, Any]]:
        """Fetch current Shadowfax orders and retain delivery-failure/NDR records."""
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            response = await self._request(
                "GET", "/v3/clients/orders/", params={"page": page, "count": 100}
            )
            payload = self._json(response, "list_ndr_shipments")
            values = payload.get("results") or payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(values, list):
                raise ProviderError(
                    "Shadowfax returned an invalid order-list response.",
                    provider="shadowfax", operation="list_ndr_shipments",
                )
            for item in values:
                if not isinstance(item, dict):
                    continue
                text = " ".join(str(item.get(key) or "") for key in (
                    "status", "status_display", "failure_reason", "ndr_reason", "remarks"
                )).casefold()
                if any(marker in text for marker in ("ndr", "undeliver", "not delivered", "delivery failed")):
                    rows.append(item)
            if not values or (isinstance(payload, dict) and not payload.get("next")):
                return rows
            page += 1

    async def cancel_booking(self, shipment: dict[str, Any]) -> dict[str, Any]:
        request_id = str(shipment.get("awb") or shipment.get("provider_order_id") or "").strip()
        if not request_id:
            raise ProviderError("Shadowfax cancellation requires an AWB or client order ID.", provider="shadowfax", operation="cancellation")
        response = await self._request(
            "POST", "/v3/clients/orders/cancel/",
            json={"request_id": request_id, "cancel_remarks": "Request cancelled by customer"},
        )
        payload = self._json(response, "cancellation")
        if not isinstance(payload, dict):
            raise ProviderError("Shadowfax returned an invalid cancellation response.", provider="shadowfax", operation="cancellation")
        code = payload.get("responseCode")
        message = str(payload.get("responseMsg") or "")
        cancelled = code == 200 and message in {
            "Request has been marked as cancelled",
            "The request is already in its cancellation phase",
        }
        return {
            "cancelled": cancelled,
            "status": "cancelled" if cancelled else "queued" if code == 304 else "rejected",
            "message": message,
            "provider_response": payload,
        }

    async def download_label(self, shipment: dict[str, Any]) -> tuple[bytes, str, str | None]:
        raise ProviderConfigurationError(
            "The official Shadowfax Unified API specification does not document a shipping-label endpoint.",
            provider="shadowfax", operation="label",
        )
