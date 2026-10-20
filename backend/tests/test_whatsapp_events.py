"""Tests for Meta webhook payload parsing."""

from app.services.whatsapp_events import parse_whatsapp_events


def _payload():
    return {"object": "whatsapp_business_account", "entry": [{"changes": [
        {"field": "messages", "value": {
            "metadata": {"phone_number_id": "123"},
            "messages": [{"id": "wamid.1", "from": "919999999999", "type": "text", "text": {"body": "Hello"}}],
        }}
    ]}]}


def test_inbound_text_extracted():
    events = parse_whatsapp_events(_payload())
    assert len(events) == 1
    assert events[0].message_id == "wamid.1"
    assert events[0].text == "Hello"


def test_status_events_ignored():
    payload = _payload()
    payload["entry"][0]["changes"][0]["value"]["messages"] = []
    payload["entry"][0]["changes"][0]["value"]["statuses"] = [{"id": "wamid.1"}]
    assert parse_whatsapp_events(payload) == []


def test_invalid_payload_ignored():
    assert parse_whatsapp_events(None) == []
    assert parse_whatsapp_events({"object": "other"}) == []


def test_non_text_messages_ignored():
    payload = _payload()
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "image"
    assert parse_whatsapp_events(payload) == []
