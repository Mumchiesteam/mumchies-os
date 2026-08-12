import pytest

from scripts import shadowfax_batch_diagnostic as script


def test_direct_transport_uses_exact_token_authorization_header_without_request():
    from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport

    transport = ShadowfaxHTTPTransport(token=" 99e4085c73c49e5d684944d15a54f09f048d69c7 ", base_url="https://api.shadowfax.example")

    assert transport._headers == {
        "Authorization": "Token 99e4085c73c49e5d684944d15a54f09f048d69c7",
        "Content-Type": "application/json",
    }


def valid_payload(number="324823"):
    location = {"name": "Mumchies Foods", "contact": "9999999999", "address_line_1": "Warehouse", "city": "Bengaluru", "state": "Karnataka", "pincode": 560076}
    return {
        "order_type": "warehouse",
        "order_details": {"client_order_id": number, "client_name": "Mumchies Foods", "actual_weight": 500, "volumetric_weight": 100, "product_value": 400, "payment_mode": "COD", "cod_amount": 400, "total_amount": 400, "order_service": "regular"},
        "customer_details": {"name": "Customer", "contact": "9999999999", "address_line_1": "Home", "city": "Pune", "state": "Maharashtra", "pincode": 411001},
        "pickup_details": dict(location), "rto_details": dict(location),
        "product_details": [{"sku_name": "Snack", "price": 400, "additional_details": {"quantity": 1}}],
    }


def test_payload_has_exact_safe_merchant_mapping_and_redacted_curl():
    payload = valid_payload()
    script._validate_payload(payload)
    curl = script._redacted_curl("https://api.shadowfax.example", payload)
    assert payload["order_details"]["client_name"] == "Mumchies Foods"
    assert "client_id" not in str(payload) and "unique_code" not in str(payload)
    assert "[REDACTED]" in curl
    assert "real-token" not in curl


@pytest.mark.anyio
async def test_first_create_failure_stops_batch_without_second_post(monkeypatch):
    calls = []
    rows = [script.Preflight(number=n, payment="COD", amount=400, pincode="411001", package_ok=True, serviceable=True, ready=True, service="regular", payload=valid_payload(n)) for n in script.ORDER_NUMBERS[:2]]

    class Transport:
        def __init__(self, **_kwargs): pass
        async def create_booking(self, payload):
            from app.services.courier_platform.base import ProviderError
            calls.append(payload["order_details"]["client_order_id"])
            raise ProviderError("rejected", provider="shadowfax", operation="booking")

    async def orders(): return {row.number: object() for row in rows}
    async def preflight(number, _order, _adapter): return next(row for row in rows if row.number == number) if number in {row.number for row in rows} else script.Preflight(number=number, error="not ready")
    monkeypatch.setattr(script, "_load_orders", orders)
    monkeypatch.setattr(script, "_preflight", preflight)
    monkeypatch.setattr("app.services.courier_platform.shadowfax_http.ShadowfaxHTTPTransport", Transport)
    monkeypatch.setattr("app.core.config.settings.shadowfax_token", "configured-token")
    monkeypatch.setattr("app.core.config.settings.shadowfax_base_url", "https://api.shadowfax.example")

    result = await script.run(input_fn=lambda _prompt: "BOOK SHADOWFAX 324823 ONCE")

    assert result == 1
    assert calls == ["324823"]


@pytest.mark.anyio
async def test_each_success_requires_fresh_confirmation_and_tracks_read_only(monkeypatch):
    creates, tracks, prompts = [], [], []
    rows = [script.Preflight(number=n, payment="Prepaid", amount=400, pincode="411001", package_ok=True, serviceable=True, ready=True, service="regular", payload=valid_payload(n)) for n in script.ORDER_NUMBERS[:2]]
    answers = iter(("BOOK SHADOWFAX 324823 ONCE", "wrong"))

    class Transport:
        def __init__(self, **_kwargs): pass
        async def create_booking(self, payload):
            number = payload["order_details"]["client_order_id"]; creates.append(number)
            return {"awb": f"AWB-{number}", "provider_order_id": f"ID-{number}", "shipment_id": f"ID-{number}"}
        async def track_shipment(self, shipment):
            tracks.append(shipment["awb"])
            return {"status": "new"}

    async def orders(): return {row.number: object() for row in rows}
    async def preflight(number, _order, _adapter): return next((row for row in rows if row.number == number), script.Preflight(number=number, error="not ready"))
    def confirm(prompt): prompts.append(prompt); return next(answers)
    monkeypatch.setattr(script, "_load_orders", orders)
    monkeypatch.setattr(script, "_preflight", preflight)
    monkeypatch.setattr("app.services.courier_platform.shadowfax_http.ShadowfaxHTTPTransport", Transport)
    monkeypatch.setattr("app.core.config.settings.shadowfax_token", "configured-token")
    monkeypatch.setattr("app.core.config.settings.shadowfax_base_url", "https://api.shadowfax.example")

    result = await script.run(input_fn=confirm)

    assert result == 0
    assert creates == ["324823"] and tracks == ["AWB-324823"]
    assert len(prompts) == 2 and "324827" in prompts[1]
