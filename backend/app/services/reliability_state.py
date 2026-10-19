"""Durable, deliberately narrow controls for address propagation and booking commands."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.shiprocket import AddressSyncOperation, BookingReservation, OrderAddressState


class StaleAddressRevision(RuntimeError): pass
class AddressSyncInProgress(RuntimeError): pass
class BookingReserved(RuntimeError): pass


def _now() -> datetime: return datetime.now(timezone.utc)


def commit_address_revision(db: Session, order_id: str, expected_revision: int, address: dict, verified: bool) -> OrderAddressState:
    state = db.get(OrderAddressState, order_id)
    if state is None:
        # Legacy JSON history remains readable; its displayed revision bootstraps the
        # durable authority exactly once.
        state = OrderAddressState(order_id=order_id, revision=expected_revision, address=None, verified=False, sync_status="not_started", updated_at=_now())
        db.add(state)
        try:
            db.commit()
        except IntegrityError:
            db.rollback(); state = db.get(OrderAddressState, order_id)
    assert state is not None
    if state.sync_lease_revision is not None:
        raise AddressSyncInProgress(str(state.sync_lease_revision))
    now = _now()
    changed = db.execute(update(OrderAddressState).where(
        OrderAddressState.order_id == order_id, OrderAddressState.revision == expected_revision,
        OrderAddressState.sync_lease_revision.is_(None),
    ).values(revision=expected_revision + 1, address=address, verified=verified,
             sync_status="pending", sync_error=None, updated_at=now)).rowcount
    if changed != 1:
        db.rollback()
        current = db.get(OrderAddressState, order_id)
        raise StaleAddressRevision(str(current.revision if current else 0))
    db.execute(update(AddressSyncOperation).where(AddressSyncOperation.order_id == order_id,
        AddressSyncOperation.status.in_(["pending", "failed"])).values(status="superseded", completed_at=now))
    db.add(AddressSyncOperation(id=uuid4().hex, order_id=order_id, revision=expected_revision + 1,
        address=address, status="pending", attempts=0, created_at=now))
    db.commit()
    return db.get(OrderAddressState, order_id)


def current_address(db: Session, order_id: str) -> OrderAddressState | None:
    return db.get(OrderAddressState, order_id)


ADDRESS_SYNC_LEASE_SECONDS = 15 * 60  # longer than all configured Shopify HTTP timeouts
BOOKING_RESERVATION_SECONDS = 5 * 60


def claim_address_sync(db: Session, order_id: str, revision: int) -> AddressSyncOperation | None:
    """Acquire a short DB lease before network I/O; another process cannot run this revision."""
    state = db.get(OrderAddressState, order_id)
    job = db.query(AddressSyncOperation).filter_by(order_id=order_id, revision=revision).one_or_none()
    if state is None or job is None or state.revision != revision or job.status not in {"pending", "failed"}:
        return None
    now, token = _now(), uuid4().hex
    acquired = db.execute(update(OrderAddressState).where(OrderAddressState.order_id == order_id,
        OrderAddressState.revision == revision, OrderAddressState.sync_lease_revision.is_(None)).values(
            sync_lease_revision=revision, sync_lease_token=token,
            sync_lease_expires_at=now + timedelta(seconds=ADDRESS_SYNC_LEASE_SECONDS))).rowcount
    if acquired != 1:
        db.rollback(); return None
    db.execute(update(AddressSyncOperation).where(AddressSyncOperation.id == job.id,
        AddressSyncOperation.status.in_(["pending", "failed"])).values(status="running", attempts=AddressSyncOperation.attempts + 1, error=None, lease_token=token))
    db.commit()
    return db.get(AddressSyncOperation, job.id)


def finish_address_sync(db: Session, order_id: str, revision: int, lease_token: str, *, status: str, error: str | None = None) -> bool:
    """Only the still-current revision may update visible state/results."""
    state = db.get(OrderAddressState, order_id)
    now = _now()
    owns = bool(state and state.sync_lease_token == lease_token and state.sync_lease_revision == revision)
    if not owns:
        return False
    db.execute(update(AddressSyncOperation).where(AddressSyncOperation.order_id == order_id,
        AddressSyncOperation.revision == revision, AddressSyncOperation.lease_token == lease_token).values(status=status, error=error, completed_at=now))
    current = state.revision == revision
    db.execute(update(OrderAddressState).where(OrderAddressState.order_id == order_id,
        OrderAddressState.sync_lease_revision == revision, OrderAddressState.sync_lease_token == lease_token).values(sync_lease_revision=None, sync_lease_token=None, sync_lease_expires_at=None,
        sync_status=status if current else OrderAddressState.sync_status,
        sync_error=error if current else OrderAddressState.sync_error, updated_at=now))
    db.commit()
    return current


def recover_interrupted_address_syncs(db: Session) -> list[tuple[str, int, dict]]:
    """Only expired leases are recoverable; a rolling deploy never steals live work."""
    now = _now()
    expired_states = db.query(OrderAddressState).filter(OrderAddressState.sync_lease_expires_at.is_not(None), OrderAddressState.sync_lease_expires_at < now).all()
    expired_tokens = {state.sync_lease_token for state in expired_states}
    running = db.query(AddressSyncOperation).filter(AddressSyncOperation.status == "running", AddressSyncOperation.lease_token.in_(expired_tokens)).all() if expired_tokens else []
    for job in running:
        job.status, job.error, job.completed_at = "failed", "worker restarted before completion", now
    if expired_tokens:
        db.execute(update(OrderAddressState).where(OrderAddressState.sync_lease_token.in_(expired_tokens)).values(
            sync_lease_revision=None, sync_lease_token=None, sync_lease_expires_at=None,
            sync_status="failed", sync_error="address-sync lease expired before completion", updated_at=now))
    db.commit()
    jobs = db.query(AddressSyncOperation).filter(AddressSyncOperation.status.in_(["pending", "failed"])).order_by(AddressSyncOperation.created_at).all()
    return [(job.order_id, job.revision, dict(job.address)) for job in jobs]


def reserve_booking(db: Session, order_id: str, provider: str, context_hash: str) -> BookingReservation:
    now = _now()
    reservation = BookingReservation(order_id=order_id, idempotency_key=uuid4().hex, provider=provider,
        context_hash=context_hash, state="reserved", attempts=0, created_at=now, updated_at=now)
    db.add(reservation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(BookingReservation, order_id)
        # A process can die after atomically reserving a command but before it has
        # crossed the provider-request boundary.  That is safe to release after a
        # bounded lease: provider_request_started_at is the durable fence which
        # distinguishes it from a possibly accepted request.  This conditional
        # update is also the cross-worker arbitration point.
        refreshed = db.execute(update(BookingReservation).where(
            BookingReservation.order_id == order_id,
            or_(
                BookingReservation.state == "failed",
                and_(
                    BookingReservation.state == "reserved",
                    BookingReservation.provider_request_started_at.is_(None),
                    BookingReservation.updated_at < now - timedelta(seconds=BOOKING_RESERVATION_SECONDS),
                ),
            ),
        ).values(idempotency_key=uuid4().hex, provider=provider, context_hash=context_hash,
                 state="reserved", error=None, completed_at=None, updated_at=now).execution_options(
                     synchronize_session=False)).rowcount
        if refreshed == 1:
            db.commit()
            return db.get(BookingReservation, order_id)
        db.rollback()
        existing = db.get(BookingReservation, order_id)
        raise BookingReserved(existing.state if existing else "reserved")
    return reservation


def booking_submitted(db: Session, order_id: str) -> None:
    db.execute(update(BookingReservation).where(BookingReservation.order_id == order_id,
        BookingReservation.state == "reserved").values(state="submitted", attempts=BookingReservation.attempts + 1,
        provider_request_started_at=_now(), updated_at=_now()))
    db.commit()


def booking_failed_before_provider_request(db: Session, order_id: str, error: str) -> None:
    """Release only a reservation which has not crossed the provider POST fence."""
    db.execute(update(BookingReservation).where(
        BookingReservation.order_id == order_id,
        BookingReservation.state == "reserved",
        BookingReservation.provider_request_started_at.is_(None),
    ).values(state="failed", error=error, completed_at=_now(), updated_at=_now()))
    db.commit()


def booking_finished(db: Session, order_id: str, *, state: str, error: str | None = None) -> None:
    db.execute(update(BookingReservation).where(BookingReservation.order_id == order_id).values(
        state=state, error=error, completed_at=_now(), updated_at=_now()))
    db.commit()
