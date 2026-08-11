from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from openpyxl import Workbook
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.courier_issue import CourierIssue
from app.models.shiprocket import ShiprocketShipment
from app.models.shipment_event import ShipmentEvent
from app.models.user import User

router = APIRouter(prefix="/courier-issues", tags=["courier-issues"])

ISSUE_TYPES = ["Damaged Return", "Lost Shipment", "RTO Issue", "Delivery Issue", "Fake Delivery Attempt", "Weight Dispute", "Billing / Charge Dispute", "Claim / Refund Pending", "Other"]
COURIERS = ["Shiprocket", "Delhivery", "Shadowfax", "Other"]


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


class CourierIssuePayload(BaseModel):
    awb: str = Field(min_length=1, max_length=128)
    date_raised: date
    raised_by: str = Field(min_length=1, max_length=120)
    courier: str = Field(min_length=1, max_length=120)
    issue_type: str
    notes: str | None = Field(default=None, max_length=5000)
    status: str = "open"
    closure_date: date | None = None

    @field_validator("awb", "raised_by", "courier", "issue_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required.")
        return value

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None


def _validate(payload: CourierIssuePayload) -> None:
    if payload.issue_type not in ISSUE_TYPES:
        raise HTTPException(422, "Select a valid issue type.")
    if payload.status not in {"open", "closed"}:
        raise HTTPException(422, "Status must be Open or Closed.")
    if payload.status == "closed" and payload.closure_date is None:
        payload.closure_date = _today()
    if payload.status == "open":
        payload.closure_date = None
    if payload.closure_date and payload.closure_date < payload.date_raised:
        raise HTTPException(422, "Closure Date cannot be before Date Raised.")


def _mapped_shipment(db: Session, awb: str) -> ShiprocketShipment | None:
    matches = list(db.scalars(select(ShiprocketShipment).where(ShiprocketShipment.awb == awb)).all())
    return matches[0] if len(matches) == 1 else None


def _mapped_order_number(db: Session, shipment: ShiprocketShipment | None, awb: str) -> str | None:
    if shipment is None:
        return None
    values = set(db.scalars(select(ShipmentEvent.order_number).where(ShipmentEvent.order_id == shipment.order_id, ShipmentEvent.awb == awb, ShipmentEvent.order_number.is_not(None))).all())
    return next(iter(values)) if len(values) == 1 else None


def _public(db: Session, issue: CourierIssue, today: date | None = None) -> dict[str, object]:
    today = today or _today()
    end = issue.closure_date if issue.status == "closed" and issue.closure_date else today
    shipment = _mapped_shipment(db, issue.awb)
    return {
        "id": issue.id, "awb": issue.awb, "date_raised": issue.date_raised.isoformat(),
        "raised_by": issue.raised_by, "courier": issue.courier, "issue_type": issue.issue_type,
        "notes": issue.notes, "status": issue.status,
        "closure_date": issue.closure_date.isoformat() if issue.closure_date else None,
        "age": max(0, (end - issue.date_raised).days),
        "order_id": shipment.order_id if shipment else None,
        "order_number": _mapped_order_number(db, shipment, issue.awb),
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
    }


def _query(db: Session, status_value: str, search: str = "", courier: str = "", issue_type: str = "", raised_by: str = "") -> list[CourierIssue]:
    query = select(CourierIssue).where(CourierIssue.status == status_value)
    if search.strip(): query = query.where(CourierIssue.awb.ilike(f"%{search.strip()}%"))
    if courier: query = query.where(CourierIssue.courier == courier)
    if issue_type: query = query.where(CourierIssue.issue_type == issue_type)
    if raised_by: query = query.where(CourierIssue.raised_by == raised_by)
    return list(db.scalars(query.order_by(CourierIssue.date_raised.asc(), CourierIssue.id.asc())).all())


@router.get("/options")
def options(db: Session = Depends(get_db)) -> dict[str, object]:
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.display_name)).all()
    return {"raised_by": [user.display_name for user in users], "couriers": COURIERS, "issue_types": ISSUE_TYPES}


@router.get("")
def list_issues(status_value: str = "open", search: str = "", courier: str = "", issue_type: str = "", raised_by: str = "", db: Session = Depends(get_db)) -> dict[str, object]:
    if status_value not in {"open", "closed"}: raise HTTPException(422, "Invalid status filter.")
    items = [_public(db, issue) for issue in _query(db, status_value, search, courier, issue_type, raised_by)]
    all_issues = list(db.scalars(select(CourierIssue)).all())
    today = _today()
    return {"items": items, "kpis": {
        "open": sum(issue.status == "open" for issue in all_issues),
        "open_over_7": sum(issue.status == "open" and (today - issue.date_raised).days > 7 for issue in all_issues),
        "open_over_15": sum(issue.status == "open" and (today - issue.date_raised).days > 15 for issue in all_issues),
        "closed_this_month": sum(issue.status == "closed" and issue.closure_date and issue.closure_date.year == today.year and issue.closure_date.month == today.month for issue in all_issues),
    }}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_issue(payload: CourierIssuePayload, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    _validate(payload)
    issue = CourierIssue(**payload.model_dump())
    db.add(issue); db.commit(); db.refresh(issue)
    return _public(db, issue)


@router.put("/{issue_id}")
def update_issue(issue_id: int, payload: CourierIssuePayload, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    _validate(payload)
    issue = db.get(CourierIssue, issue_id)
    if not issue: raise HTTPException(404, "Courier issue not found.")
    for field, value in payload.model_dump().items(): setattr(issue, field, value)
    db.commit(); db.refresh(issue)
    return _public(db, issue)


@router.get("/export.xlsx")
def export_issues(status_value: str = "open", search: str = "", courier: str = "", issue_type: str = "", raised_by: str = "", db: Session = Depends(get_db)) -> Response:
    rows = [_public(db, issue) for issue in _query(db, status_value, search, courier, issue_type, raised_by)]
    workbook = Workbook(); sheet = workbook.active; sheet.title = "Courier Issues"
    sheet.append(["AWB", "Date Raised", "Closure Date", "Age", "Raised By", "Courier", "Issue Type", "Notes", "Status", "Order Number"])
    for row in rows: sheet.append([row["awb"], row["date_raised"], row["closure_date"], row["age"], row["raised_by"], row["courier"], row["issue_type"], row["notes"], str(row["status"]).title(), row["order_number"]])
    output = BytesIO(); workbook.save(output)
    filename = f"courier-issues-{_today().isoformat()}.xlsx"
    return Response(output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
