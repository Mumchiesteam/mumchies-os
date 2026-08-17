from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case as sql_case, func, or_, select
from sqlalchemy.orm import Session

from app.core.identity import current_user
from app.db.session import get_db
from app.models.ndr import NDRCase, NDREvent, NDRImportRun
from app.models.user import User
from app.services.ndr import add_event, serialize_case
from app.services.ndr_import import import_ndr, serialize_import_run
from app.services.ndr_delivery import resolve_active_terminal_cases
from app.services.ndr_eligibility import DELIVERY_EXCEPTIONS, PRE_PICKUP_STATES, is_ndr_eligible
from app.services.order_read_models import by_order_number
from app.core.config import settings
import hmac

router = APIRouter(prefix="/ndr", tags=["ndr"])


class NDRAction(BaseModel):
    action: Literal["add_note", "assign", "customer_contacted", "courier_contacted", "resolve", "reopen"]
    note: str | None = Field(default=None, max_length=2000)
    assigned_to_user_id: int | None = None
    resolution_outcome: Literal["delivered", "rto_confirmed"] | None = None


class NDRImportRow(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    order_id: str = Field(default="", max_length=160)
    awb: str = Field(default="", max_length=160)
    customer_name: str = Field(default="", max_length=300)
    phone: str = Field(default="", max_length=64)
    city: str = Field(default="", max_length=160)
    status: str = Field(default="", max_length=300)
    failure_reason: str = Field(default="", max_length=2000)
    attempts: int = Field(default=0, ge=0, le=100)
    last_update: datetime | None = None
    recommended_action: str = Field(default="", max_length=1000)
    whatsapp_message: str = Field(default="", max_length=5000)
    whatsapp_url: str = Field(default="", max_length=8000)


class NDRImportPayload(BaseModel):
    schema_version: int
    run_id: str = Field(min_length=1, max_length=160)
    generated_at: datetime
    source_health: dict[str, Any]
    source_counts: dict[str, Any]
    rows: list[NDRImportRow]

    @field_validator("schema_version")
    @classmethod
    def require_version_one(cls, value: int) -> int:
        if value != 1: raise ValueError("schema_version must be 1")
        return value


@router.post("/import")
def import_cases(payload: NDRImportPayload, request: Request, db: Session = Depends(get_db)) -> dict:
    authorization = request.headers.get("Authorization", "")
    provided = authorization[7:] if authorization.startswith("Bearer ") else ""
    expected = settings.ndr_ingest_token or ""
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Invalid NDR import credentials.")
    existing = db.scalar(select(NDRImportRun).where(NDRImportRun.run_id == payload.run_id))
    if existing:
        return serialize_import_run(existing, idempotent=True)
    try:
        return serialize_import_run(import_ndr(db, payload))
    except Exception:
        db.rollback()
        raise


@router.get("/operators")
def operators(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": u.id, "display_name": u.display_name, "username": u.username} for u in db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.display_name)).all()]


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc); today = now.date()
    cases = db.scalars(select(NDRCase)).all()
    aware = lambda value: value if not value or value.tzinfo else value.replace(tzinfo=timezone.utc)
    active = [c for c in cases if c.current_status != "resolved" and c.source_lifecycle == "active" and is_ndr_eligible(c.provider_status, c.failure_reason)]
    last = db.scalar(select(NDRImportRun).order_by(NDRImportRun.received_at.desc()).limit(1))
    successful = db.scalar(select(NDRImportRun).where(NDRImportRun.status.in_(["completed", "partial_success"])).order_by(NDRImportRun.received_at.desc()).limit(1))
    return {"active_ndr": len(active), "new_today": sum(1 for c in cases if aware(c.first_ndr_at).date() == today), "awaiting_customer": sum(c.current_status == "awaiting_customer" for c in active), "courier_pending": sum(c.current_status == "courier_pending" for c in active), "resolved_today": sum(bool(c.resolved_at and aware(c.resolved_at).date() == today) for c in cases), "over_sla": sum((now - aware(c.first_ndr_at)).total_seconds() > 172800 for c in active), "last_sync_at": last.received_at.isoformat() if last else None, "last_successful_import_at": successful.received_at.isoformat() if successful else None, "last_sync_status": last.status if last else None, "last_sync_error": "; ".join(last.safe_errors or []) if last else None, "source_health": successful.source_health if successful else None, "source_counts": successful.source_counts if successful else None, "last_import_run_id": successful.run_id if successful else None}


@router.get("/cases")
def list_cases(search: str = "", courier: str = "", failure_reason: str = "", ageing: str = "", assigned_to: int | None = None, status: str = "", priority: str = "", kpi: Literal["active", "new_today", "awaiting_customer", "courier_pending", "resolved_today", "over_sla"] | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    request_started = time.perf_counter()
    terminal_started = time.perf_counter()
    resolve_active_terminal_cases(db)
    terminal_ms = (time.perf_counter() - terminal_started) * 1000
    query = select(NDRCase)
    normalized_status = func.lower(func.replace(func.replace(func.trim(func.coalesce(NDRCase.provider_status, "")), "_", " "), "-", " "))
    normalized_reason = func.lower(func.replace(func.replace(func.trim(func.coalesce(NDRCase.failure_reason, "")), "_", " "), "-", " "))
    combined_status = normalized_status + " " + normalized_reason
    eligible_active = normalized_status.not_in(PRE_PICKUP_STATES) & normalized_reason.not_in(PRE_PICKUP_STATES) & or_(*(combined_status.contains(marker) for marker in DELIVERY_EXCEPTIONS))
    now = datetime.now(timezone.utc)
    if kpi is None and not status:
        query = query.where(NDRCase.source_lifecycle == "active", NDRCase.current_status != "resolved", eligible_active)
    elif kpi == "active": query = query.where(NDRCase.source_lifecycle == "active", NDRCase.current_status != "resolved", eligible_active)
    elif kpi == "new_today": query = query.where(NDRCase.first_ndr_at >= datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc))
    elif kpi == "awaiting_customer": query = query.where(NDRCase.source_lifecycle == "active", NDRCase.current_status == "awaiting_customer", eligible_active)
    elif kpi == "courier_pending": query = query.where(NDRCase.source_lifecycle == "active", NDRCase.current_status == "courier_pending", eligible_active)
    elif kpi == "resolved_today": query = query.where(NDRCase.current_status == "resolved", NDRCase.resolved_at >= datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc))
    elif kpi == "over_sla": query = query.where(NDRCase.source_lifecycle == "active", NDRCase.current_status != "resolved", NDRCase.first_ndr_at < now - timedelta(hours=72), eligible_active)
    if search: query = query.where(or_(NDRCase.order_number.ilike(f"%{search}%"), NDRCase.awb.ilike(f"%{search}%"), NDRCase.customer_name.ilike(f"%{search}%"), NDRCase.customer_phone.ilike(f"%{search}%")))
    if courier: query = query.where(NDRCase.provider == courier)
    if failure_reason: query = query.where(NDRCase.failure_reason.ilike(f"%{failure_reason}%"))
    if assigned_to is not None: query = query.where(NDRCase.assigned_to_user_id == assigned_to)
    if status: query = query.where(NDRCase.current_status == status)
    if priority: query = query.where(NDRCase.priority == priority)
    if ageing in {"0-24", "24-48", "48+"}:
        if ageing == "0-24": query = query.where(NDRCase.first_ndr_at >= now - timedelta(hours=24))
        elif ageing == "24-48": query = query.where(NDRCase.first_ndr_at < now - timedelta(hours=24), NDRCase.first_ndr_at >= now - timedelta(hours=48))
        else: query = query.where(NDRCase.first_ndr_at < now - timedelta(hours=48))
    count = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    priority_rank = sql_case((NDRCase.priority == "high", 0), (NDRCase.priority == "medium", 1), else_=2)
    rows = db.scalars(query.order_by(NDRCase.resolved_at.is_not(None), priority_rank, NDRCase.first_ndr_at.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    cached = by_order_number(db, {str(row.order_number or row.order_id or "").lstrip("#") for row in rows})
    changed = False
    for row in rows:
        order = cached.get(str(row.order_number or row.order_id or "").lstrip("#"))
        if order and order.products and row.products != order.products:
            row.products = order.products; changed = True
    if changed: db.commit()
    logging.getLogger(__name__).info(
        "ndr_cases total_ms=%.2f terminal_ms=%.2f query_enrich_ms=%.2f rows=%d",
        (time.perf_counter() - request_started) * 1000, terminal_ms,
        (time.perf_counter() - request_started) * 1000 - terminal_ms, len(rows),
    )
    return {"items": [serialize_case(c) for c in rows], "total": count, "page": page, "page_size": page_size}


@router.get("/cases/{case_id}")
def case_detail(case_id: str, db: Session = Depends(get_db)) -> dict:
    case = db.get(NDRCase, case_id)
    if not case: raise HTTPException(404, "NDR case not found.")
    events = db.scalars(select(NDREvent).where(NDREvent.case_id == case_id).order_by(NDREvent.created_at.desc())).all()
    return serialize_case(case, events=events)


def _analytics_row(cases: list[NDRCase]) -> dict:
    delivered = sum(case.resolution_outcome == "delivered" for case in cases)
    rto = sum(case.resolution_outcome == "rto_confirmed" for case in cases)
    known = delivered + rto
    durations = [(_aware(case.resolved_at) - _aware(case.first_ndr_at)).total_seconds() / 3600 for case in cases if case.resolved_at and case.resolution_outcome in {"delivered", "rto_confirmed"}]
    return {"resolved_cases": known, "delivered": delivered, "rto_confirmed": rto, "resolution_percent": round(delivered * 100 / known, 1) if known else None, "avg_resolution_hours": round(sum(durations) / len(durations), 1) if durations else None}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("/analytics")
def resolution_analytics(period: Literal["today", "7d", "30d", "custom"] = "30d", start: datetime | None = None, end: datetime | None = None, db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    if period == "today": start_at = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
    elif period == "7d": start_at = now - timedelta(days=7)
    elif period == "30d": start_at = now - timedelta(days=30)
    else:
        if not start or not end: raise HTTPException(422, "Custom analytics requires start and end.")
        start_at, now = _aware(start), _aware(end)
    cases = db.scalars(select(NDRCase).where(NDRCase.first_ndr_at >= start_at, NDRCase.first_ndr_at <= now)).all()
    resolved = [case for case in cases if case.resolution_outcome in {"delivered", "rto_confirmed"} and case.resolved_at]
    core = _analytics_row(cases)
    def groups(field: str) -> list[dict]:
        values: dict[str, list[NDRCase]] = {}
        for case in cases:
            key = str(getattr(case, field) or "Unknown")
            values.setdefault(key, []).append(case)
        return [{field: key, **_analytics_row(rows)} for key, rows in sorted(values.items())]
    contacted = {}
    for key, field in (("customer_contacted", "customer_contacted_at"), ("courier_contacted", "courier_contacted_at")):
        relevant = [case for case in cases if getattr(case, field)]
        contacted[key] = {"cases": len(relevant), **_analytics_row(relevant)} if relevant else None
    return {"period":{"start":start_at.isoformat(),"end":now.isoformat()},"total_cases":len(cases),"open_cases":sum(case.current_status != "resolved" and case.source_lifecycle == "active" for case in cases),"resolved_cases":len(resolved),**core,"by_courier":groups("provider"),"by_failure_reason":groups("failure_reason"),"contacted":contacted}


@router.post("/sync")
async def sync_now() -> dict:
    raise HTTPException(410, "Direct courier sync is disabled. NDR data is imported from GitHub Actions.")


@router.post("/cases/{case_id}/actions")
def case_action(case_id: str, payload: NDRAction, request: Request, db: Session = Depends(get_db)) -> dict:
    actor = current_user(request); case = db.get(NDRCase, case_id)
    if not case: raise HTTPException(404, "NDR case not found.")
    now = datetime.now(timezone.utc); note = (payload.note or "").strip()
    descriptions = {"add_note": note, "customer_contacted": note or "Customer contacted.", "courier_contacted": note or "Courier contacted.", "resolve": note or "Case resolved.", "reopen": note or "Case reopened."}
    if payload.action == "assign":
        assignee = db.get(User, payload.assigned_to_user_id) if payload.assigned_to_user_id else None
        if not assignee or not assignee.is_active: raise HTTPException(422, "Select an active operator.")
        case.assigned_to_user_id = assignee.id; case.assigned_to_name = assignee.display_name; description = f"Assigned to {assignee.display_name}."
    elif payload.action == "add_note":
        if not note: raise HTTPException(422, "Note is required.")
        description = note
    elif payload.action == "customer_contacted": case.customer_contacted_at = now; case.current_status = "courier_pending"; description = descriptions[payload.action]
    elif payload.action == "courier_contacted": case.courier_contacted_at = now; case.current_status = "awaiting_customer"; description = descriptions[payload.action]
    elif payload.action == "resolve":
        if payload.resolution_outcome not in {"delivered", "rto_confirmed"}: raise HTTPException(422, "Select Delivered or RTO Confirmed.")
        case.current_status = "resolved"; case.source_lifecycle = "resolved"; case.resolved_at = now
        case.resolution_outcome = payload.resolution_outcome; case.resolution_source = "manual"
        case.resolved_by_user_id = actor.id; case.resolved_by_name = actor.display_name
        case.resolution_note = note or None; description = f"Resolved as {payload.resolution_outcome.replace('_', ' ').title()}."
    else:
        case.current_status = "new"; case.source_lifecycle = "active"; case.resolved_at = None; case.resolution_note = None
        case.resolution_outcome = None; case.resolution_source = None; case.resolved_by_user_id = None; case.resolved_by_name = None; description = descriptions[payload.action]
    event_data = {"note": note} if note else {}
    if payload.action == "resolve": event_data.update({"resolution_outcome": payload.resolution_outcome, "resolution_source": "manual"})
    add_event(db, case, payload.action, description, actor=actor, data=event_data or None); db.commit(); db.refresh(case)
    return serialize_case(case)
