"""Persistent WhatsApp conversation ownership and message deduplication."""
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import mapped_column
from app.db.base import Base


class SupportConversation(Base):
    __tablename__ = "support_conversations"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel = mapped_column(String(24), nullable=False, default="whatsapp")
    phone_number_id = mapped_column(String(80), nullable=False)
    customer_id = mapped_column(String(80), nullable=False)
    mode = mapped_column(String(12), nullable=False, default="human")
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("channel", "phone_number_id", "customer_id", name="uq_support_conversation_identity"),)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id = mapped_column(Integer, ForeignKey("support_conversations.id"), nullable=False, index=True)
    provider_message_id = mapped_column(String(255), nullable=False, unique=True)
    direction = mapped_column(String(16), nullable=False)
    message_type = mapped_column(String(24), nullable=False, default="text")
    body = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
