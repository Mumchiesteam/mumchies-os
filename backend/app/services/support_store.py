"""Database helpers for durable, human-first WhatsApp conversation state.

These functions are not yet wired to the public webhook. The database migration
must be applied and end-to-end tests passed before enabling ingestion.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.support_conversation import SupportConversation, SupportMessage
from app.services.support_handover import ConversationMode, decide_handover


def record_incoming_text(
    db: Session, *, phone_number_id: str, customer_id: str,
    message_id: str, body: str, requires_human: bool = False,
) -> tuple[SupportConversation, bool]:
    """Persist an inbound message once. New conversations start human-owned.

    Returns (conversation, is_new_message). Does not send any WhatsApp reply.
    Caller must own the transaction; failures roll back the transaction.
    """
    if not all((phone_number_id, customer_id, message_id)) or not body.strip():
        raise ValueError("Missing WhatsApp message identity or text")
    existing_message = db.scalar(select(SupportMessage).where(SupportMessage.provider_message_id == message_id))
    if existing_message is not None:
        conversation = db.get(SupportConversation, existing_message.conversation_id)
        if conversation is None:
            raise ValueError("Orphaned support message")
        return conversation, False
    conversation = db.scalar(
        select(SupportConversation).where(
            SupportConversation.channel == "whatsapp",
            SupportConversation.phone_number_id == phone_number_id,
            SupportConversation.customer_id == customer_id,
        ).with_for_update()
    )
    if conversation is None:
        conversation = SupportConversation(
            channel="whatsapp", phone_number_id=phone_number_id,
            customer_id=customer_id, mode=ConversationMode.HUMAN.value,
        )
        db.add(conversation)
        db.flush()
    decision = decide_handover(
        body,
        current_mode=ConversationMode(conversation.mode),
        requires_human=requires_human,
    )
    conversation.mode = decision.mode.value
    db.add(SupportMessage(
        conversation_id=conversation.id, provider_message_id=message_id,
        direction="inbound", message_type="text", body=body[:2000],
    ))
    db.flush()
    return conversation, True
