from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ndr import NDRCase, NDREvent, NDRImportRun


COURIER_FIELDS = (
    "order_id", "order_number", "provider", "courier_name", "city", "customer_name",
    "customer_phone", "provider_status", "failure_reason", "delivery_attempts",
    "last_provider_update_at", "recommended_action", "whatsapp_message", "whatsapp_url",
)


def identity_for(source: str, order_id: str, awb: str) -> str | None:
    clean_awb = awb.strip().upper()
    if clean_awb:
        return f"awb:{clean_awb}"
    clean_source, clean_order = source.strip().casefold(), order_id.strip().lstrip("#")
    return f"fallback:{clean_source}:{clean_order}" if clean_source and clean_order else None


def _dt(value: datetime | None, fallback: datetime) -> datetime:
    if value is None: return fallback
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, datetime) and isinstance(right, datetime):
        return _dt(left, left).astimezone(timezone.utc) == _dt(right, right).astimezone(timezone.utc)
    return left == right


def import_ndr(db: Session, payload: Any) -> NDRImportRun:
    # Serialize retries of the same GitHub run before checking idempotency.
    # The lock is transaction-scoped and therefore releases on commit/rollback.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(payload.run_id))))
    existing_run = db.scalar(select(NDRImportRun).where(NDRImportRun.run_id == payload.run_id))
    if existing_run:
        return existing_run

    now = datetime.now(timezone.utc); created = updated = unchanged = rejected = 0; errors: list[str] = []
    seen_by_source: dict[str, set[str]] = {}
    for index, row in enumerate(payload.rows):
        source = row.source.strip().casefold(); order_id = row.order_id.strip().lstrip("#"); awb = row.awb.strip().upper()
        identity = identity_for(source, order_id, awb)
        if identity is None:
            rejected += 1; errors.append(f"Row {index + 1}: source/order identity is missing."); continue
        seen_by_source.setdefault(source, set()).add(identity)
        case = db.scalar(select(NDRCase).where(NDRCase.source_identity == identity))
        row_time = _dt(row.last_update, _dt(payload.generated_at, now))
        values = {
            "order_id": order_id or None, "order_number": order_id or None, "provider": source,
            "courier_name": source.title(), "city": row.city or None, "customer_name": row.customer_name or None,
            "customer_phone": row.phone or None, "provider_status": row.status or None,
            "failure_reason": row.failure_reason or None, "delivery_attempts": row.attempts,
            "last_provider_update_at": row_time, "recommended_action": row.recommended_action or None,
            "whatsapp_message": row.whatsapp_message or None, "whatsapp_url": row.whatsapp_url or None,
        }
        if case is None:
            case = NDRCase(
                id=str(uuid4()), awb=awb or None, source_identity=identity, first_ndr_at=row_time,
                current_status="new", source_lifecycle="active", last_synced_at=now,
                products=[], cod_amount=0, raw_provider_data=None, **values,
            )
            db.add(case); db.flush()
            db.add(NDREvent(id=str(uuid4()), case_id=case.id, event_type="case_created",
                description=f"Imported from {source.title()}.", actor_name="GitHub NDR Import",
                event_data={"run_id": payload.run_id}))
            created += 1
        else:
            changed = any(not _equal(getattr(case, key), value) for key, value in values.items())
            for key, value in values.items(): setattr(case, key, value)
            case.awb = awb or None; case.last_synced_at = now
            if case.current_status == "resolved": case.source_lifecycle = "resolved"
            else: case.source_lifecycle = "active"
            if changed:
                db.add(NDREvent(id=str(uuid4()), case_id=case.id, event_type="import_update",
                    description=f"Courier data refreshed from {source.title()}.", actor_name="GitHub NDR Import",
                    event_data={"run_id": payload.run_id}))
                updated += 1
            else: unchanged += 1

    health = payload.source_health if isinstance(payload.source_health, dict) else {}
    successful_sources = {str(name).casefold() for name, value in health.items() if isinstance(value, dict) and str(value.get("status") or "").casefold() in {"success", "ok", "completed"}}
    for source in successful_sources:
        present = seen_by_source.get(source, set())
        for case in db.scalars(select(NDRCase).where(NDRCase.provider == source)).all():
            if case.source_identity not in present:
                case.source_lifecycle = "resolved" if case.current_status == "resolved" else "no_longer_reported"

    statuses = [str(value.get("status") or "").casefold() for value in health.values() if isinstance(value, dict)]
    failed_sources = [value for value in statuses if value in {"failed", "error"}]
    succeeded_sources = [value for value in statuses if value in {"success", "ok", "completed"}]
    status = "partial_success" if failed_sources and succeeded_sources else "failed" if failed_sources and not succeeded_sources else "completed"
    run = NDRImportRun(
        id=str(uuid4()), run_id=payload.run_id, schema_version=payload.schema_version,
        generated_at=_dt(payload.generated_at, now), received_at=now, status=status,
        source_health=payload.source_health, source_counts=payload.source_counts,
        rows_received=len(payload.rows), created=created, updated=updated, unchanged=unchanged,
        rejected=rejected, safe_errors=errors or None,
    )
    db.add(run); db.commit(); db.refresh(run); return run


def serialize_import_run(run: NDRImportRun, *, idempotent: bool = False) -> dict[str, Any]:
    return {
        "run_id": run.run_id, "status": run.status, "idempotent": idempotent,
        "generated_at": run.generated_at.isoformat(), "received_at": run.received_at.isoformat(),
        "rows_received": run.rows_received, "created": run.created, "updated": run.updated,
        "unchanged": run.unchanged, "rejected": run.rejected, "source_counts": run.source_counts,
        "safe_errors": run.safe_errors or [],
    }
