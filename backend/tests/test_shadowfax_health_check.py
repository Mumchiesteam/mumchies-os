import pytest

from app.services import shadowfax_diagnostics as diagnostics


@pytest.mark.anyio
async def test_shadowfax_health_check_uses_only_read_only_auth_and_serviceability(monkeypatch):
    calls: list[str] = []

    class Transport:
        def __init__(self, *, token, base_url):
            assert token == "canonical-token"
            assert base_url == "https://shadowfax.example/api"

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
