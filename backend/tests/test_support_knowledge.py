"""Offline knowledge base quality checks; no API keys or WhatsApp required."""
import json

from app.services.support_knowledge import KB_PATH, lookup_draft_faq


def test_knowledge_base_has_sources_and_review_flags():
    data = json.loads(KB_PATH.read_text(encoding="utf-8"))
    assert len(data["entries"]) >= 20
    assert all(entry["source"].startswith("https://mumchies.com/") for entry in data["entries"])
    assert all(entry["approval"] == "pending" for entry in data["entries"])


def test_product_catalogue_question_is_answered():
    result = lookup_draft_faq("what products do you deal with?")
    assert result["matched_intent"] == "catalogue"
    assert result["needs_human"] is False


def test_hinglish_catalogue_question_is_answered():
    result = lookup_draft_faq("products batao")
    assert result["matched_intent"] == "catalogue"


def test_refund_escalates():
    assert lookup_draft_faq("I need a refund")["needs_human"] is True


def test_unknown_question_does_not_permanently_pause_bot():
    result = lookup_draft_faq("Can you explain something unusual?")
    assert result["needs_human"] is False
    assert result["matched_intent"] is None


def test_allergy_question_requests_human_review():
    result = lookup_draft_faq("Does it have sesame allergy risk?")
    assert result["needs_human"] is True
