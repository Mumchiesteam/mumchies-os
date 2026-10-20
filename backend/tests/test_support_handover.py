"""Isolated tests for conservative WhatsApp support handover."""

from app.services.support_handover import ConversationMode, decide_handover


def test_regular_message_allows_bot():
    result = decide_handover("What are your products?")
    assert result.mode == ConversationMode.BOT
    assert result.send_automated_reply is True


def test_customer_requests_person():
    result = decide_handover("I want to speak to someone")
    assert result.mode == ConversationMode.HUMAN
    assert result.send_automated_reply is False


def test_staff_reply_pauses_bot():
    result = decide_handover("Hi", staff_message_detected=True)
    assert result.mode == ConversationMode.HUMAN
    assert result.send_automated_reply is False


def test_existing_human_mode_never_resumes_automatically():
    result = decide_handover("What is the price?", current_mode=ConversationMode.HUMAN)
    assert result.mode == ConversationMode.HUMAN
    assert result.send_automated_reply is False


def test_refund_escalation():
    result = decide_handover("Refund please", requires_human=True)
    assert result.mode == ConversationMode.HUMAN
    assert result.send_automated_reply is False
