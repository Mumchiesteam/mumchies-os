from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case as sql_case, func, or_, select
from sqlalchemy.orm import Session

from app.core.identity import current_user
from app.db.session import get_db
from app.models.ndr import NDRCase, NDREvent, NDRSyncRun
from app.models.user import User
from app.services.ndr import NDRSyncAlreadyRunning, add_event, serialize_case, sync_ndr

router = APIRouter(prefix="/ndr", tags=["ndr"])


class NDRAction(BaseModel):
    action: Literal["add_note", "assign", "customer_contacted", "courier_contacted", "resolve", "reopen"]
    note: str | None = Field(default=None, max_length=2000)
    assigned_to_user_id: int | None = None


@router.get("/operators")
def operators(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": u.id, "display_name": u.display_name, "username": u.username} for u in db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.display_name)).all()]


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc); today = now.date()
    cases = db.scalars(select(NDRCase)).all()
    aware = lambda value: value if not value or value.tzinfo else value.replace(tzinfo=timezone.utc)
    active = [c for c in cases if c.current_status != "resolved"]
    last = db.scalar(select(NDRSyncRun).order_by(NDRSyncRun.started_at.desc()).limit(1))
    return {"active_ndr": len(active), "new_today": sum(1 for c in cases if aware(c.first_ndr_at).date() == today), "awaiting_customer": sum(c.current_status == "awaiting_customer" for c in active), "courier_pending": sum(c.current_status == "courier_pending" for c in active), "resolved_today": sum(bool(c.resolved_at and aware(c.resolved_at).date() == today) for c in cases), "over_sla": sum((now - aware(c.first_ndr_at)).total_seconds() > 172800 for c in active), "last_sync_at": last.completed_at.isoformat() if last and last.completed_at else None, "last_sync_status": last.status if last else None}


@router.get("/cases")
def list_cases(search: str = "", courier: str = "", failure_reason: str = "", ageing: str = "", assigned_to: int | None = None, status: str = "", priority: str = "", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    query = select(NDRCase)
    if search: query = query.where(or_(NDRCase.order_number.ilike(f"%{search}%"), NDRCase.awb.ilike(f"%{search}%"), NDRCase.customer_name.ilike(f"%{search}%"), NDRCase.customer_phone.ilike(f"%{search}%")))
    if courier: query = query.where(NDRCase.provider == courier)
    if failure_reason: query = query.where(NDRCase.failure_reason.ilike(f"%{failure_reason}%"))
    if assigned_to is not None: query = query.where(NDRCase.assigned_to_user_id == assigned_to)
    if status: query = query.where(NDRCase.current_status == status)
    if priority: query = query.where(NDRCase.priority == priority)
    if ageing in {"0-24", "24-48", "48+"}:
        now = datetime.now(timezone.utc)
        if ageing == "0-24": query = query.where(NDRCase.first_ndr_at >= now - timedelta(hours=24))
        elif ageing == "24-48": query = query.where(NDRCase.first_ndr_at < now - timedelta(hours=24), NDRCase.first_ndr_at >= now - timedelta(hours=48))
        else: query = query.where(NDRCase.first_ndr_at < now - timedelta(hours=48))
    count = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    priority_rank = sql_case((NDRCase.priority == "high", 0), (NDRCase.priority == "medium", 1), else_=2)
    rows = db.scalars(query.order_by(NDRCase.resolved_at.is_not(None), priority_rank, NDRCase.first_ndr_at.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [serialize_case(c) for c in rows], "total": count, "page": page, "page_size": page_size}


@router.get("/cases/{case_id}")
def case_detail(case_id: str, db: Session = Depends(get_db)) -> dict:
    case = db.get(NDRCase, case_id)
    if not case: raise HTTPException(404, "NDR case not found.")
    events = db.scalars(select(NDREvent).where(NDREvent.case_id == case_id).order_by(NDREvent.created_at.desc())).all()
    return serialize_case(case, events=events)


@router.post("/sync")
async def sync_now(request: Request, db: Session = Depends(get_db)) -> dict:
    try: run = await sync_ndr(db, trigger="manual", actor=current_user(request))
    except NDRSyncAlreadyRunning as error: raise HTTPException(409, str(error)) from error
    return {"id": run.id, "status": run.status, "cases_seen": run.cases_seen, "cases_created": run.cases_created, "cases_updated": run.cases_updated, "completed_at": run.completed_at.isoformat() if run.completed_at else None}


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
    elif payload.action == "resolve": case.current_status = "resolved"; case.resolved_at = now; case.resolution_note = note or None; description = descriptions[payload.action]
    else: case.current_status = "new"; case.resolved_at = None; case.resolution_note = None; description = descriptions[payload.action]
    add_event(db, case, payload.action, description, actor=actor, data={"note": note} if note else None); db.commit(); db.refresh(case)
    return serialize_case(case)
