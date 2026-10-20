"""Parse Meta WhatsApp webhook events without side effects or storing PII."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WhatsAppEvent:
    message_id: str
    phone_number_id: str
    sender_id: str
    text: str
    kind: str


def parse_whatsapp_events(payload: object) -> list[WhatsAppEvent]:
    """Return only supported inbound text messages; ignore status and echo events."""
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return []
    events: list[WhatsAppEvent] = []
    for entry in payload.get("entry", []):
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []):
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") or {}
            phone_id = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
            for message in value.get("messages", []):
                if not isinstance(message, dict) or message.get("type") != "text":
                    continue
                body = message.get("text")
                text = body.get("body") if isinstance(body, dict) else None
                message_id = message.get("id")
                sender = message.get("from")
                if not all(isinstance(x, str) and x for x in (phone_id, message_id, sender, text)):
                    continue
                events.append(WhatsAppEvent(message_id, phone_id, sender, text[:2000], "inbound_text"))
    return events
