from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.services.courier_platform.base import ProviderError
from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport

SAFE_TEST_PINCODE = "560076"
EXPECTED_CLIENT_NAME = "Mumchies Foods"
EXPECTED_CLIENT_ID = "4500"
SHADOWFAX_360_LOGIN_URL = "https://shadowfax360.in/api/v1/login/"
SHADOWFAX_SHOPIFY_ORDERS_URL = "https://dale.shadowfax.in/api/v2/shopify/orders/"
# Uvicorn configures this logger with its stderr handler in production, which
# Render captures as Application Logs. Module INFO loggers are not enabled there.
logger = logging.getLogger("uvicorn.error")


def _check(status: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "message": message, **extra}


def _token_diagnostic_metadata() -> tuple[str, str, dict[str, Any]]:
    raw_api_token = settings.shadowfax_api_token
    source = "SHADOWFAX_API_TOKEN" if raw_api_token else "fallback SHADOWFAX_TOKEN"
    raw_token = settings.shadowfax_effective_token or ""
    trimmed_token = raw_token.strip()
    return raw_token, trimmed_token, {
        "source": source,
        "length": len(trimmed_token),
        "last4": trimmed_token[-4:] if trimmed_token else None,
        "has_surrounding_whitespace": raw_token != trimmed_token,
        "quoted": len(trimmed_token) >= 2 and trimmed_token[0] == trimmed_token[-1] and trimmed_token[0] in {"'", '"'},
    }


def _redact_token(value: object, raw_token: str, trimmed_token: str) -> str:
    text = str(value)
    token_values = {raw_token, trimmed_token}
    if len(trimmed_token) >= 2 and trimmed_token[0] == trimmed_token[-1] and trimmed_token[0] in {"'", '"'}:
        token_values.add(trimmed_token[1:-1])
    for secret in token_values - {""}:
        text = text.replace(secret, "[redacted]")
    return text


def _log_health_request(event: dict[str, Any], *, raw_token: str, trimmed_token: str, token_metadata: dict[str, Any]) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    if event["event"] == "request":
        logger.info(
            "shadowfax_health_request timestamp=%s method=%s url=%s auth_scheme=Token token_source=%s token_length=%s token_last4=%s quoted=%s trimmed_whitespace=%s authorization_attached=%s",
            timestamp,
            event["method"],
            event["url"],
            token_metadata["source"],
            token_metadata["length"],
            token_metadata["last4"],
            token_metadata["quoted"],
            token_metadata["has_surrounding_whitespace"],
            event["authorization_attached"],
        )
        return
    logger.info(
        "shadowfax_health_response timestamp=%s method=%s url=%s status=%s content_type=%s body=%s location=%s headers=%s",
        timestamp,
        event["method"],
        event["url"],
        event["status"],
        event["content_type"],
        _redact_token(event.get("body"), raw_token, trimmed_token),
        event["location"],
        event["headers"],
    )


async def shadowfax_health_check() -> dict[str, Any]:
    """Run only documented GET checks. This function never creates or changes a shipment."""
    token_present = bool(settings.shadowfax_effective_token and settings.shadowfax_effective_token.strip())
    base_url_present = bool(settings.shadowfax_base_url and settings.shadowfax_base_url.strip())
    configuration = _check(
        "PASS" if token_present and base_url_present else "FAIL",
        "Shadowfax configuration is present." if token_present and base_url_present else "SHADOWFAX_API_TOKEN (or legacy SHADOWFAX_TOKEN) and SHADOWFAX_BASE_URL are required.",
        token_present=token_present,
        base_url_present=base_url_present,
    )
    authentication = _check("FAIL", "Authentication was not attempted.")
    serviceability = _check("FAIL", "Serviceability was not attempted.", test_pincode=SAFE_TEST_PINCODE)
    client_mapping = _check(
        "not_verifiable",
        "The documented read-only Shadowfax response does not expose client name or client ID.",
        expected_client_name=EXPECTED_CLIENT_NAME,
        expected_client_id=EXPECTED_CLIENT_ID,
    )
    create_order_api = _check(
        "not_safely_testable_without_mutation",
        "The documented create-order endpoint is POST-only and was not called.",
    )
    shadowfax_status_code: int | None = None

    if token_present and base_url_present:
        try:
            raw_token, trimmed_token, token_metadata = _token_diagnostic_metadata()
            transport = ShadowfaxHTTPTransport(
                token=raw_token,
                base_url=settings.shadowfax_base_url or "",
                request_observer=lambda event: _log_health_request(
                    event,
                    raw_token=raw_token,
                    trimmed_token=trimmed_token,
                    token_metadata=token_metadata,
                ),
            )
            authenticated = await transport.authenticate()
            authentication = _check("PASS" if authenticated else "FAIL", "Token authentication succeeded." if authenticated else "Shadowfax did not accept the configured token.")
            raw = await transport.serviceability({"delivery_pincode": SAFE_TEST_PINCODE})
            shadowfax_status_code = raw.get("http_status") if isinstance(raw.get("http_status"), int) else None
            serviceable = bool(raw.get("serviceable"))
            serviceability = _check(
                "PASS" if serviceable else "FAIL",
                "Shadowfax returned serviceability for the safe test pincode." if serviceable else str(raw.get("reason") or "Shadowfax did not return serviceability for the safe test pincode."),
                test_pincode=SAFE_TEST_PINCODE,
            )
        except ProviderError as error:
            shadowfax_status_code = error.http_status
            target = authentication if authentication["status"] != "PASS" else serviceability
            target.update(_check("FAIL", str(error), test_pincode=SAFE_TEST_PINCODE) if target is serviceability else _check("FAIL", str(error)))

    overall = "PASS" if configuration["status"] == authentication["status"] == serviceability["status"] == "PASS" else "FAIL"
    message = "Shadowfax read-only checks passed." if overall == "PASS" else next(
        check["message"] for check in (configuration, authentication, serviceability) if check["status"] == "FAIL"
    )
    return {
        "overall": overall,
        "configuration": configuration,
        "authentication": authentication,
        "serviceability": serviceability,
        "client_mapping": client_mapping,
        "create_order_api": create_order_api,
        "shadowfax_status_code": shadowfax_status_code,
        "message": message,
    }


def _shadowfax_text(value: object) -> str:
    return str(value or "").strip()


def _shadowfax_channel_row(row: dict[str, Any]) -> dict[str, object]:
    """Expose only routing identifiers/statuses, never customer or address data."""
    status_info = row.get("status_info") if isinstance(row.get("status_info"), dict) else {}
    return {
        "shadowfax_channel_row_id": row.get("channel_order_id") or row.get("channel_id") or row.get("id") or row.get("order_id"),
        "shopify_order_id": row.get("shopify_order_id") or row.get("id"),
        "client_order_reference": row.get("client_order_id") or row.get("order_name") or row.get("name") or row.get("reference_id"),
        "status": row.get("status") or status_info.get("status_label") or status_info.get("status_code"),
        "payment_mode": row.get("payment_mode") or row.get("payment_type"),
        "awb": row.get("awb_number") or row.get("awb"),
        "channel": row.get("channel") or row.get("channel_name") or row.get("platform") or row.get("source"),
    }


def _shadowfax_reference_matches(reference: object, *, order_number: str, shopify_name: str | None) -> bool:
    candidate = _shadowfax_text(reference)
    expected = {_shadowfax_text(order_number), _shadowfax_text(shopify_name)} - {""}
    return candidate in expected


async def _shadowfax_360_token(client: httpx.AsyncClient) -> str:
    """Get the same e-commerce token used by the 360 channel-order UI, without logging secrets."""
    if settings.shadowfax_email and settings.shadowfax_password_secret:
        response = await client.post(
            SHADOWFAX_360_LOGIN_URL,
            json={"email": settings.shadowfax_email, "password": settings.shadowfax_password_secret},
        )
        if response.status_code == 200:
            payload = response.json()
            nested = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
            token = payload.get("token") if isinstance(payload, dict) else None
            token = token or (payload.get("auth_token") if isinstance(payload, dict) else None)
            token = token or nested.get("token") or nested.get("auth_token")
            if _shadowfax_text(token):
                return _shadowfax_text(token)
    token = _shadowfax_text(settings.shadowfax_effective_token)
    if token:
        return token
    raise ProviderError("Shadowfax 360 credentials are not configured.", provider="shadowfax", operation="channel_order_lookup")


async def shadowfax_shopify_order_diagnostic(
    *, shopify_order_id: str, order_number: str, shopify_name: str | None, client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    """Read-only resolver for the existing Shadowfax Shopify-channel order.

    This deliberately uses only the 360 Shopify list endpoint.  It never calls
    Unified API direct-create (/v3/clients/orders/) or any Ship Now endpoint.
    """
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
    try:
        token = await _shadowfax_360_token(http_client)
        response = await http_client.post(
            SHADOWFAX_SHOPIFY_ORDERS_URL,
            headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
            json={"page": 1, "limit": 250, "status": "all", "shopify_order_id": shopify_order_id, "payment_type": None},
        )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        raw_rows = payload.get("data") if isinstance(payload, dict) else None
        rows = raw_rows if isinstance(raw_rows, list) else []
        evaluations: list[dict[str, object]] = []
        accepted_rows: list[dict[str, object]] = []
        for item in rows:
            raw = item if isinstance(item, dict) else {}
            safe = _shadowfax_channel_row(raw)
            id_matches = _shadowfax_text(safe["shopify_order_id"]) == _shadowfax_text(shopify_order_id)
            reference_matches = _shadowfax_reference_matches(
                safe["client_order_reference"], order_number=order_number, shopify_name=shopify_name,
            )
            accepted = id_matches and reference_matches
            reason = "accepted: Shopify internal ID and order reference match"
            if not id_matches:
                reason = "rejected: Shopify internal ID does not match"
            elif not reference_matches:
                reason = "rejected: client/order reference does not match"
            evaluation = {"row": safe, "accepted": accepted, "reason": reason}
            evaluations.append(evaluation)
            if accepted:
                accepted_rows.append(evaluation)

        matched = accepted_rows[0]["row"] if len(accepted_rows) == 1 else None
        resolver_reason = (
            "matched uniquely"
            if matched
            else "no valid row matched Shopify internal ID and order reference"
            if not accepted_rows
            else "multiple valid rows matched Shopify internal ID and order reference"
        )
        return {
            "shopify_internal_order_id": shopify_order_id,
            "shopify_display_order_number": order_number,
            "shopify_display_order_name": shopify_name,
            "http_status": response.status_code,
            "top_level_json_keys": sorted(str(key) for key in payload.keys()) if isinstance(payload, dict) else [],
            "returned_row_count": len(rows),
            "rows": evaluations,
            "resolver_result": {
                "found": matched is not None,
                "reason": resolver_reason,
                "matched_shadowfax_channel_row_id": matched.get("shadowfax_channel_row_id") if isinstance(matched, dict) else None,
                "shopify_internal_order_id": matched.get("shopify_order_id") if isinstance(matched, dict) else None,
                "client_order_reference": matched.get("client_order_reference") if isinstance(matched, dict) else None,
                "status": matched.get("status") if isinstance(matched, dict) else None,
                "awb": matched.get("awb") if isinstance(matched, dict) else None,
            },
        }
    except httpx.HTTPError as error:
        raise ProviderError("Shadowfax Shopify-order lookup request failed.", provider="shadowfax", operation="channel_order_lookup") from error
    finally:
        if owns_client:
            await http_client.aclose()
