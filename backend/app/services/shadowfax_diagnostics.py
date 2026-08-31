from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.services.courier_platform.base import ProviderError
from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport

SAFE_TEST_PINCODE = "560076"
EXPECTED_CLIENT_NAME = "Mumchies Foods"
EXPECTED_CLIENT_ID = "4500"
logger = logging.getLogger(__name__)


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
