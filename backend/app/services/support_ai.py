"""First-stage Mumchies support responder; no external calls."""


def answer_support_message(message: str) -> dict[str, object]:
    """Return a safe, deterministic reply without accessing customer data."""
    text = message.strip().lower()
    if not text or len(text) > 2000:
        raise ValueError("Message must contain 1 to 2000 characters")
    if any(term in text for term in ("refund", "cancel", "damaged", "return")):
        return {"reply": "Our support team will review your request.", "needs_human": True}
    if any(term in text for term in ("order", "tracking", "delivery", "awb")):
        return {"reply": "Our team can check your order after verification.", "needs_human": True}
    if "laddu" in text and "sugar" in text:
        return {"reply": "Our Dry Fruit Laddu has no added refined sugar or jaggery. Dates and dried fruits contain naturally occurring sugars.", "needs_human": False}
    return {"reply": "Thanks for contacting Mumchies. Our team will help you.", "needs_human": True}
