from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.courier_platform.base import ProviderError
from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport

SAFE_TEST_PINCODE = "560076"
EXPECTED_CLIENT_NAME = "Mumchies Foods"
EXPECTED_CLIENT_ID = "4500"


def _check(status: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "message": message, **extra}


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
            transport = ShadowfaxHTTPTransport(token=settings.shadowfax_effective_token or "", base_url=settings.shadowfax_base_url or "")
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
