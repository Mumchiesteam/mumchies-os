"""Offline WhatsApp support simulator: authenticated internal endpoint only.

Does not store conversations or contact Meta. Production support integration
will use a separate verified, persistent pipeline.
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.support_simulator_ai import simulate_contextual_reply
from app.services.support_knowledge import lookup_draft_faq
from app.services.support_handover import ConversationMode, decide_handover

router = APIRouter(prefix="/support/simulator", tags=["support-simulator"])


class SimulationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    mode: ConversationMode = ConversationMode.BOT
    history: list[dict[str, str]] = Field(default_factory=list, max_length=16)


@router.post("/message")
async def simulate_message(payload: SimulationRequest) -> dict[str, object]:
    baseline = await simulate_contextual_reply(payload.message, payload.history) if payload.mode == ConversationMode.BOT else lookup_draft_faq(payload.message)
    decision = decide_handover(
        payload.message, current_mode=payload.mode,
        requires_human=bool(baseline["needs_human"]),
    )
    if not decision.send_automated_reply:
        return {
            "reply": "Our team will help you shortly." if payload.mode == ConversationMode.BOT else None,
            "mode": ConversationMode.HUMAN.value,
            "needs_human": True,
            "simulated": True, "ai_used": False,
        }
    return {"reply": baseline["reply"], "mode": decision.mode.value,
            "needs_human": False, "simulated": True, "ai_used": baseline.get("ai_used", False)}
