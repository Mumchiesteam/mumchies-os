"""Offline support simulator checks."""
import asyncio
from app.api.routes.support_simulator import SimulationRequest, simulate_message
from app.services.support_handover import ConversationMode


def test_safe_product_question_gets_bot_reply():
    result = asyncio.run(simulate_message(SimulationRequest(message="Does your laddu have sugar?")))
    assert result["simulated"] is True
    assert result["mode"] == "bot"
    assert result["reply"]


def test_refund_escalates_to_human():
    result = asyncio.run(simulate_message(SimulationRequest(message="I want a refund")))
    assert result["mode"] == "human"
    assert result["needs_human"] is True


def test_human_conversation_does_not_get_bot_reply():
    result = asyncio.run(simulate_message(SimulationRequest(message="Hello", mode=ConversationMode.HUMAN)))
    assert result["reply"] is None
    assert result["mode"] == "human"


def test_handover_does_not_send_bot_reply():
    result = asyncio.run(simulate_message(SimulationRequest(message="I want a refund")))
    assert result["reply"] is None
    assert result["ai_used"] is False
