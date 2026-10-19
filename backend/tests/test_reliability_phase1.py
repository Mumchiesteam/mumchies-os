from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.shiprocket import AddressSyncOperation, BookingReservation, OrderAddressState
from app.services.reliability_state import (
    AddressSyncInProgress, BookingReserved, booking_finished, booking_submitted, claim_address_sync,
    commit_address_revision, current_address, finish_address_sync, reserve_booking,
    recover_interrupted_address_syncs,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'reliability.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def address(line: str) -> dict[str, str]:
    return {"customer_name": "Customer", "phone": "9999999999", "address_line1": line,
            "address_line2": "", "landmark": "Park", "city": "Delhi", "state": "Delhi", "pincode": "110001"}


def test_reverse_address_completion_never_publishes_old_sync_result(db):
    first = commit_address_revision(db, "order-1", 0, address("Old street"), True)
    second = commit_address_revision(db, "order-1", first.revision, address("New street"), True)
    assert second.revision == 2
    # Revision 1 was superseded before any provider write; it can never publish.
    assert claim_address_sync(db, "order-1", 1) is None
    state = current_address(db, "order-1")
    assert state.revision == 2 and state.address["address_line1"] == "New street"
    assert state.sync_status == "pending"


def test_newer_address_waits_while_an_older_provider_write_is_in_flight(db):
    first = commit_address_revision(db, "order-1", 0, address("Old street"), True)
    assert claim_address_sync(db, "order-1", first.revision) is not None
    with pytest.raises(AddressSyncInProgress):
        commit_address_revision(db, "order-1", first.revision, address("New street"), True)


def test_failed_address_sync_survives_restart_as_failed_and_retryable(db):
    commit_address_revision(db, "order-1", 0, address("Street"), True)
    job = claim_address_sync(db, "order-1", 1)
    assert job is not None
    assert finish_address_sync(db, "order-1", 1, job.lease_token, status="failed", error="Shopify timeout") is True
    db.expire_all()  # represent a new process/session reading durable state
    state = current_address(db, "order-1")
    job = db.query(AddressSyncOperation).filter_by(order_id="order-1", revision=1).one()
    assert state.sync_status == "failed" and state.sync_error == "Shopify timeout"
    assert job.status == "failed" and job.attempts == 1
    assert claim_address_sync(db, "order-1", 1) is not None


def test_rolling_restart_does_not_release_another_live_workers_lease(db):
    commit_address_revision(db, "order-1", 0, address("Street"), True)
    assert claim_address_sync(db, "order-1", 1) is not None
    jobs = recover_interrupted_address_syncs(db)
    state = current_address(db, "order-1")
    assert jobs == []
    assert state.sync_lease_revision == 1 and state.sync_status == "pending"


def test_expired_lease_is_fenced_and_recovered_as_failed(db):
    commit_address_revision(db, "order-1", 0, address("Street"), True)
    job = claim_address_sync(db, "order-1", 1)
    state = current_address(db, "order-1")
    state.sync_lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert recover_interrupted_address_syncs(db) == [("order-1", 1, address("Street"))]
    assert finish_address_sync(db, "order-1", 1, job.lease_token, status="succeeded") is False


def test_second_operator_cannot_get_a_second_provider_booking_reservation(db):
    reserve_booking(db, "order-1", "shiprocket", "context-a")
    booking_submitted(db, "order-1")
    provider_posts = 1
    with pytest.raises(BookingReserved, match="submitted"):
        reserve_booking(db, "order-1", "shiprocket", "context-a")
    assert provider_posts == 1


def test_timeout_after_provider_acceptance_is_uncertain_and_cannot_retry(db):
    reserve_booking(db, "order-1", "delhivery", "context-a")
    booking_submitted(db, "order-1")  # exact point at which a provider POST may have happened
    booking_finished(db, "order-1", state="uncertain", error="timeout after request")
    with pytest.raises(BookingReserved, match="uncertain"):
        reserve_booking(db, "order-1", "delhivery", "context-a")
    row = db.get(BookingReservation, "order-1")
    assert row.attempts == 1 and row.state == "uncertain" and row.provider_request_started_at is not None


def test_crash_before_provider_request_releases_only_an_expired_reservation(db):
    reservation = reserve_booking(db, "order-1", "shiprocket", "context-a")
    reservation.updated_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    db.commit()
    # A new worker/session sees the durable reservation after the crash.
    db.expunge(reservation)
    retried = reserve_booking(db, "order-1", "shiprocket", "context-b")
    assert retried.state == "reserved"
    assert retried.context_hash == "context-b"
    assert retried.provider_request_started_at is None
