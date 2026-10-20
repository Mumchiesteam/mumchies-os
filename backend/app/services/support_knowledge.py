"""Draft, source-backed FAQ matching for the offline simulator only.

Do not use this module for live customer replies until business approval.
"""
import json
import re
from pathlib import Path

KB_PATH = Path(__file__).resolve().parents[1] / "data" / "support_knowledge_base.json"
_ESCALATION = ("refund", "return", "cancel", "damaged", "missing item", "complaint",
               "where is my order", "track my order", "tracking number", "awb",
               "speak to human", "speak to a human", "talk to a person", "agent",
               "real person", "customer care executive", "call me")


def _normalise(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold()))


def lookup_draft_faq(message: str) -> dict[str, object]:
    text = _normalise(message)
    if not text:
        raise ValueError("Message is empty")
    if any(f" {_normalise(phrase)} " in f" {text} " for phrase in _ESCALATION):
        return {"reply": "Our team will help you with this request.",
                "needs_human": True, "matched_intent": "escalation"}
    data = json.loads(KB_PATH.read_text(encoding="utf-8"))
    best = None
    score = 0
    for entry in data["entries"]:
        for phrase in entry["phrases"]:
            candidate = _normalise(phrase)
            if candidate and f" {candidate} " in f" {text} " and len(candidate) > score:
                best, score = entry, len(candidate)
    if any(phrase in text for phrase in ("u there", "you there", "anyone there", "are you there")):
        return {"reply": "Yes, I'm here! What can I help you with?", "needs_human": False, "matched_intent": "presence"}
    if "gond" in text:
        return {"reply": "I can't confirm Gond Laddu availability from this draft catalogue. Please check our current product listing or ask our team.", "needs_human": False, "matched_intent": "product_availability"}
    if any(phrase in text for phrase in ("how many days", "delivery time", "delivery timeline", "days for delviery")):
        return {"reply": "Delivery time depends on your destination. What is your six-digit delivery pincode?", "needs_human": False, "matched_intent": "delivery_timeline"}
    if "stores" in text or "stockists" in text or "retail outlets" in text:
        return {"reply": "Which city or area are you looking in? Our team can confirm current store availability.", "needs_human": False, "matched_intent": "retail_stores"}
    if best is None:
        return {"reply": "Could you share a little more detail? Our team can help if needed.",
                "needs_human": False, "matched_intent": None}
    if best["mode"] == "human_review":
        return {"reply": best["answer"], "needs_human": True, "matched_intent": best["id"]}
    return {"reply": best["answer"], "needs_human": False, "matched_intent": best["id"]}
