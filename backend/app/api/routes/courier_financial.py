from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.identity import current_user, require_owner
from app.db.session import get_db
from app.models.courier_financial import CourierFinancialAction, CourierFinancialCase, CourierFinancialLedgerEntry, CourierFinancialUnmatchedRow
from app.models.user import User
from app.services.courier_financial import STATUS, import_document, rebuild_cases, serialize_case
import uuid

router=APIRouter(prefix="/courier-reconciliation",tags=["courier reconciliation"])
class Action(BaseModel): action:str; note:str|None=None; assigned_to_user_id:int|None=None
class BulkAction(BaseModel): case_ids:list[str]; action:str; assigned_to_user_id:int|None=None; note:str|None=None
@router.get("/summary")
def summary(db:Session=Depends(get_db)):
    rebuild_cases(db); db.commit(); cases=db.scalars(select(CourierFinancialCase)).all(); active=[c for c in cases if c.os_status!="Reconciled"]
    total=lambda xs:round(sum(c.amount_at_risk or 0 for c in xs),2)
    return {"needs_action":{"count":len([c for c in active if c.os_status=="Needs Action"]),"amount":total([c for c in active if c.os_status=="Needs Action"])},"cod_pending":{"count":len([c for c in active if c.primary_issue_type in {"COD_OVERDUE","COD_SHORT"}]),"amount":total([c for c in active if c.primary_issue_type in {"COD_OVERDUE","COD_SHORT"}])},"charge_mismatch":{"count":len([c for c in active if c.primary_issue_type in {"FREIGHT_VARIANCE","WEIGHT_SLAB_JUMP"}]),"amount":total([c for c in active if c.primary_issue_type in {"FREIGHT_VARIANCE","WEIGHT_SLAB_JUMP"}])},"in_progress":{"count":len([c for c in active if c.os_status in {"Disputed","Awaiting Credit"}]),"amount":total([c for c in active if c.os_status in {"Disputed","Awaiting Credit"}])},"recovered":total([c for c in cases if c.os_status=="Recovered"])}
@router.get("/cases")
def cases(provider:str="",issue_type:str="",status:str="",age:str="",min_amount:float|None=None,db:Session=Depends(get_db)):
    q=select(CourierFinancialCase)
    if not status: q=q.where(CourierFinancialCase.os_status!="Reconciled")
    if provider:q=q.where(CourierFinancialCase.provider==provider)
    if issue_type:q=q.where(CourierFinancialCase.primary_issue_type==issue_type)
    if status:q=q.where(CourierFinancialCase.os_status==status)
    if min_amount is not None:q=q.where(CourierFinancialCase.amount_at_risk>=min_amount)
    rank={"Critical":0,"High":1,"Medium":2,"Low":3}; rows=list(db.scalars(q).all()); rows.sort(key=lambda c:(rank.get(c.priority,4),c.action_deadline or datetime.max.replace(tzinfo=timezone.utc),-(c.amount_at_risk or 0))); return {"items":[serialize_case(c) for c in rows]}
@router.get("/cases/{case_id}")
def detail(case_id:str,db:Session=Depends(get_db)):
    case=db.get(CourierFinancialCase,case_id)
    if not case:raise HTTPException(404,"Case not found.")
    return serialize_case(case,db.scalars(select(CourierFinancialLedgerEntry).where(CourierFinancialLedgerEntry.provider==case.provider,CourierFinancialLedgerEntry.awb==case.awb)).all(),db.scalars(select(CourierFinancialAction).where(CourierFinancialAction.case_id==case_id).order_by(CourierFinancialAction.created_at.desc())).all())
@router.get("/unmatched")
def unmatched(db:Session=Depends(get_db)):
    return {"items":[{"id":r.id,"provider":r.provider,"awb_or_reference":r.awb_or_reference,"amount":r.amount,"reason":r.reason,"source_row_number":r.source_row_number,"document_id":r.document_id} for r in db.scalars(select(CourierFinancialUnmatchedRow)).all()]}
@router.post("/imports")
async def upload(provider:str=Form(...),document_type:str=Form(...),period:str|None=Form(None),file:UploadFile=File(...),request:Request=None,db:Session=Depends(get_db)):
    require_owner(request); content=await file.read()
    try:result=import_document(db,provider=provider,document_type=document_type,filename=file.filename or "import.csv",content=content,period=period);db.commit();return result
    except ValueError as e:db.rollback();raise HTTPException(422,str(e))
@router.post("/cases/{case_id}/actions")
def action(case_id:str,payload:Action,request:Request,db:Session=Depends(get_db)):
    user=current_user(request); case=db.get(CourierFinancialCase,case_id)
    if not case:raise HTTPException(404,"Case not found.")
    if payload.action=="add_note":
        if not payload.note:raise HTTPException(422,"Note is required.")
    elif payload.action in STATUS: case.os_status=payload.action; case.resolved_at=datetime.now(timezone.utc) if payload.action in {"Recovered","Accepted","Reconciled"} else None
    elif payload.action=="assign":
        assignee=db.get(User,payload.assigned_to_user_id) if payload.assigned_to_user_id else None
        if not assignee:raise HTTPException(422,"Select an active operator.")
        case.assigned_to_user_id=assignee.id;case.assigned_to_name=assignee.display_name
    else: raise HTTPException(422,"Unsupported action.")
    case.action_note=payload.note or case.action_note;case.last_action_at=datetime.now(timezone.utc);db.add(CourierFinancialAction(id=str(uuid.uuid4()),case_id=case.id,action=payload.action,note=payload.note,actor_user_id=user.id,actor_name=user.display_name));db.commit();return serialize_case(case)
@router.post("/cases/bulk-actions")
def bulk(payload:BulkAction,request:Request,db:Session=Depends(get_db)):
    if payload.action not in {"Disputed","Accepted","assign"}:raise HTTPException(422,"Unsupported bulk action.")
    for case in db.scalars(select(CourierFinancialCase).where(CourierFinancialCase.id.in_(payload.case_ids))).all():
        if payload.action=="assign":
            user=db.get(User,payload.assigned_to_user_id)
            if not user:raise HTTPException(422,"Select an active operator.")
            case.assigned_to_user_id=user.id;case.assigned_to_name=user.display_name
        else:case.os_status=payload.action
    db.commit();return {"updated":len(payload.case_ids)}
