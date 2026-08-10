from scripts.shadowfax_324663_diagnostic import _json_body, _redacted_curl, _sanitize


def test_diagnostic_serialization_and_curl_redact_credentials():
    payload = {"order_details": {"client_order_id": "324663", "client_name": "Mumchies Foods"}}
    body = _json_body(payload)
    command = _redacted_curl("https://dale.shadowfax.in/api/v3/clients/orders/", body)

    assert body == '{"order_details":{"client_order_id":"324663","client_name":"Mumchies Foods"}}'
    assert "Authorization: Token [REDACTED]" in command
    assert "Mumchies Foods" in command
    assert "client_id" not in body


def test_diagnostic_response_sanitizer_removes_only_secrets():
    sanitized = _sanitize({"token": "secret", "data": {"id": 4500, "awb_number": "AWB-1"}})
    assert sanitized == {"token": "[REDACTED]", "data": {"id": 4500, "awb_number": "AWB-1"}}
