import pytest

from scripts.shadowfax_324724_diagnostic import ORDER_NUMBER, _json_body, _redacted_curl, _sanitize, _validate_payload


def test_diagnostic_serialization_and_curl_redact_credentials():
    payload = {"order_details": {"client_order_id": "324724", "client_name": "Mumchies Foods"}}
    body = _json_body(payload)
    command = _redacted_curl("https://dale.shadowfax.in/api/v3/clients/orders/", body)

    assert body == '{"order_details":{"client_order_id":"324724","client_name":"Mumchies Foods"}}'
    assert ORDER_NUMBER == "324724"
    assert "Authorization: Token [REDACTED]" in command
    assert "Mumchies Foods" in command
    assert "client_id" not in body


def test_diagnostic_response_sanitizer_removes_only_secrets():
    sanitized = _sanitize({"token": "secret", "data": {"id": 4500, "awb_number": "AWB-1"}})
    assert sanitized == {"token": "[REDACTED]", "data": {"id": 4500, "awb_number": "AWB-1"}}


def test_diagnostic_payload_validator_accepts_current_schema_and_rejects_client_id():
    address = {"name": "Name", "contact": "9876543210", "address_line_1": "Address", "city": "City", "state": "State", "pincode": 492001}
    payload = {
        "order_type": "warehouse",
        "order_details": {
            "client_order_id": "324724", "client_name": "Mumchies Foods", "actual_weight": 500,
            "volumetric_weight": 100, "product_value": 461, "payment_mode": "Prepaid",
            "cod_amount": 0, "total_amount": 461, "order_service": "regular",
        },
        "customer_details": address, "pickup_details": address, "rto_details": address,
        "product_details": [{"sku_name": "Product", "sku_id": "SKU-1", "price": 461, "additional_details": {"quantity": 1}}],
    }
    _validate_payload(payload)
    payload["order_details"]["client_id"] = 4500
    with pytest.raises(RuntimeError, match="client_id"):
        _validate_payload(payload)
