"""Conservative support handover rules; no external services required."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class ConversationMode(str, Enum):
    BOT = "bot"
    HUMAN = "human"


@dataclass(frozen=True)
class HandoverDecision:
    mode: ConversationMode
    send_automated_reply: bool
    reason: str


HUMAN_REQUEST_PHRASES = (
    "human", "real person", "talk to someone", "speak to someone",
    "customer care", "call me", "agent", "representative",
    "insaan se baat", "aadmi se baat", "person se baat",
)


def decide_handover(
    message: str,
    *,
    current_mode: ConversationMode = ConversationMode.BOT,
    staff_message_detected: bool = False,
    requires_human: bool = False,
) -> HandoverDecision:
    """Never auto-resume a human-owned conversation.

    A separate, authenticated staff action must explicitly switch HUMAN to BOT.
    """
    if current_mode == ConversationMode.HUMAN:
        return HandoverDecision(ConversationMode.HUMAN, False, "already_human_owned")
    if staff_message_detected:
        return HandoverDecision(ConversationMode.HUMAN, False, "staff_replied")
    if requires_human or any(phrase in message.casefold() for phrase in HUMAN_REQUEST_PHRASES):
        return HandoverDecision(ConversationMode.HUMAN, False, "escalation_required")
    return HandoverDecision(ConversationMode.BOT, True, "bot_allowed")
