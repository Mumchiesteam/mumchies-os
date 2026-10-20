"""SQLite unit tests for support persistence (no production DB needed)."""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.support_conversation import SupportConversation, SupportMessage
from app.services.support_store import record_incoming_text


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SupportConversation.__table__.create(engine)
    SupportMessage.__table__.create(engine)
    return Session(engine)


def test_new_conversation_is_human_owned():
    with _session() as db:
        conversation, created = record_incoming_text(
            db, phone_number_id="number1", customer_id="customer1",
            message_id="wamid.1", body="Hello",
        )
        db.commit()
        assert created
        assert conversation.mode == "human"


def test_duplicate_webhook_does_not_duplicate_message():
    with _session() as db:
        args = dict(phone_number_id="number1", customer_id="customer1",
                    message_id="wamid.1", body="Hello")
        record_incoming_text(db, **args)
        _, created = record_incoming_text(db, **args)
        db.commit()
        assert created is False
        assert len(db.scalars(select(SupportMessage)).all()) == 1


def test_different_customers_get_different_conversations():
    with _session() as db:
        first, _ = record_incoming_text(db, phone_number_id="number1",
            customer_id="customer1", message_id="wamid.1", body="Hello")
        second, _ = record_incoming_text(db, phone_number_id="number1",
            customer_id="customer2", message_id="wamid.2", body="Hello")
        assert first.id != second.id
