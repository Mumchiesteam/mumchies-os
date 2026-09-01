import pytest

from app.services import shadowfax_diagnostics as diagnostics


@pytest.mark.anyio
async def test_shadowfax_health_check_uses_only_read_only_auth_and_serviceability(monkeypatch):
    calls: list[str] = []

    class Transport:
        def __init__(self, *, token, base_url, request_observer=None):
            assert token == "canonical-token"
            assert base_url == "https://shadowfax.example/api"
            assert request_observer is not None

        async def authenticate(self):
            calls.append("authenticate")
            return True

        async def serviceability(self, request):
            calls.append("serviceability")
            assert request == {"delivery_pincode": "560076"}
            return {"serviceable": True, "http_status": 200}

    monkeypatch.setattr(diagnostics.settings, "shadowfax_api_token", "canonical-token")
    monkeypatch.setattr(diagnostics.settings, "shadowfax_token", "legacy-token")
    monkeypatch.setattr(diagnostics.settings, "shadowfax_base_url", "https://shadowfax.example/api")
    monkeypatch.setattr(diagnostics, "ShadowfaxHTTPTransport", Transport)

    result = await diagnostics.shadowfax_health_check()

    assert result["overall"] == "PASS"
    assert result["authentication"]["status"] == "PASS"
    assert result["serviceability"]["status"] == "PASS"
    assert result["client_mapping"]["status"] == "not_verifiable"
    assert result["create_order_api"]["status"] == "not_safely_testable_without_mutation"
    assert result["shadowfax_status_code"] == 200
    assert calls == ["authenticate", "serviceability"]
    assert "canonical-token" not in str(result)
    assert "legacy-token" not in str(result)


@pytest.mark.anyio
async def test_shadowfax_health_check_fails_for_missing_configuration(monkeypatch):
    monkeypatch.setattr(diagnostics.settings, "shadowfax_token", None)
    monkeypatch.setattr(diagnostics.settings, "shadowfax_api_token", None)
    monkeypatch.setattr(diagnostics.settings, "shadowfax_base_url", None)

    result = await diagnostics.shadowfax_health_check()

    assert result["overall"] == "FAIL"
    assert result["configuration"]["status"] == "FAIL"
    assert result["authentication"]["status"] == "FAIL"


def test_shadowfax_api_token_is_canonical_with_legacy_fallback(monkeypatch):
    monkeypatch.setattr(diagnostics.settings, "shadowfax_api_token", "canonical")
    monkeypatch.setattr(diagnostics.settings, "shadowfax_token", "legacy")
    assert diagnostics.settings.shadowfax_effective_token == "canonical"
    monkeypatch.setattr(diagnostics.settings, "shadowfax_api_token", None)
    assert diagnostics.settings.shadowfax_effective_token == "legacy"


def test_shadowfax_health_logging_never_emits_full_token(caplog):
    raw_token = "  'full-secret-token-69c7'\n"
    trimmed_token = raw_token.strip()
    metadata = {
        "source": "SHADOWFAX_API_TOKEN",
        "length": len(trimmed_token),
        "last4": "69c7",
        "has_surrounding_whitespace": True,
        "quoted": True,
    }

    with caplog.at_level("INFO", logger=diagnostics.logger.name):
        diagnostics._log_health_request(
            {
                "event": "request",
                "method": "GET",
                "url": "https://dale.shadowfax.in/api/v1/clients/serviceability/?pincodes=560076",
                "authorization_attached": True,
            },
            raw_token=raw_token,
            trimmed_token=trimmed_token,
            token_metadata=metadata,
        )
        diagnostics._log_health_request(
            {
                "event": "response",
                "method": "GET",
                "url": "https://dale.shadowfax.in/api/v1/clients/serviceability/?pincodes=560076",
                "status": 401,
                "content_type": "application/json",
                "body": '{"message":"full-secret-token-69c7"}',
                "location": None,
                "headers": {"server": "shadowfax"},
            },
            raw_token=raw_token,
            trimmed_token=trimmed_token,
            token_metadata=metadata,
        )

    emitted = caplog.text
    assert "shadowfax_health_request" in emitted
    assert "shadowfax_health_response" in emitted
    assert "full-secret-token-69c7" not in emitted
    assert "Authorization:" not in emitted
    assert "token_last4=69c7" in emitted
    assert "body={\"message\":\"[redacted]\"}" in emitted
