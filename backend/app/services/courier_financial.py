"""Import-only courier finance reconciliation.  No provider API is called here."""
from __future__ import annotations
import csv, hashlib, json, uuid
from datetime import datetime, timezone
from io import BytesIO, StringIO
from typing import Any
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.courier_financial import CourierFinancialCase, CourierFinancialDocument, CourierFinancialLedgerEntry, CourierFinancialUnmatchedRow, CourierSettlement
from app.models.shiprocket import ShiprocketShipment

SUPPORTED = {"shiprocket": {"cod_remittance", "ledger", "freight_vas", "weight_discrepancy"}, "delhivery": {"cod_remittance", "wallet_ledger", "invoice_awb_backup"}}
STATUS = {"Needs Action", "Disputed", "Awaiting Credit", "Recovered", "Accepted", "Reconciled"}

def _key(v: Any) -> str: return "".join(c for c in str(v or "").lower() if c.isalnum())
def _money(v: Any) -> float:
    try: return float(str(v or "0").replace(",", "").replace("₹", "").strip() or 0)
    except (ValueError, TypeError): return 0.0
def _value(row: dict[str, Any], *names: str) -> Any:
    indexed = {_key(k): v for k,v in row.items()}
    for name in names:
        if _key(name) in indexed and indexed[_key(name)] not in (None, ""): return indexed[_key(name)]
    return None
def _awb(row: dict[str, Any]) -> str:
    return str(_value(row,"awb","waybill","awb number","tracking number","shipment awb") or "").strip()
def _date(v: Any) -> datetime|None:
    if not v: return None
    if isinstance(v, datetime): return v.replace(tzinfo=v.tzinfo or timezone.utc)
    for fmt in ("%Y-%m-%d","%d-%m-%Y","%d/%m/%Y","%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(str(v).strip(),fmt).replace(tzinfo=timezone.utc)
        except ValueError: pass
    return None
def read_rows(content: bytes, filename: str) -> list[dict[str, Any]]:
    if filename.lower().endswith((".xlsx", ".xls")):
        book=load_workbook(BytesIO(content), read_only=True, data_only=True); sheet=book.active
        rows=list(sheet.iter_rows(values_only=True)); headers=[str(v or "").strip() for v in rows[0]] if rows else []
        return [{headers[i]: value for i,value in enumerate(row) if i < len(headers)} for row in rows[1:] if any(v is not None for v in row)]
    text=content.decode("utf-8-sig",errors="replace"); return list(csv.DictReader(StringIO(text)))

def component_for(document_type: str, row: dict[str, Any]) -> str:
    if document_type == "cod_remittance": return "cod_remittance"
    if document_type == "weight_discrepancy": return "weight_excess"
    description=str(_value(row,"description","transaction type","charge type","remarks") or "").lower()
    if "refund" in description or "credit" in description: return "credit_refund"
    if "rto" in description or "reverse" in description: return "rto_freight"
    if "cod" in description and "charge" in description: return "cod_fee"
    if "freight" in description or document_type in {"freight_vas","invoice_awb_backup"}: return "freight"
    return "adjustment"

def import_document(db: Session, *, provider: str, document_type: str, filename: str, content: bytes, period: str|None=None) -> dict:
    provider=provider.lower().strip(); document_type=document_type.lower().strip()
    if provider == "shadowfax": raise ValueError("Shadowfax finance imports are disabled until an account-specific sample schema is approved.")
    if document_type not in SUPPORTED.get(provider,set()): raise ValueError("Unsupported provider/document type.")
    checksum=hashlib.sha256(content).hexdigest(); existing=db.scalar(select(CourierFinancialDocument).where(CourierFinancialDocument.checksum==checksum))
    if existing: return {"document_id":existing.id,"idempotent":True,"imported":0,"unmatched":0}
    doc=CourierFinancialDocument(id=str(uuid.uuid4()),provider=provider,document_type=document_type,filename=filename,period=period,checksum=checksum,parser_version="financial-v1",source_metadata={"format":filename.rsplit('.',1)[-1].lower()}); db.add(doc)
    imported=unmatched=0
    for number,row in enumerate(read_rows(content,filename),start=2):
        cleaned={str(k): (v.isoformat() if isinstance(v,datetime) else v) for k,v in row.items()}
        raw=json.dumps(cleaned,sort_keys=True,default=str,separators=(",",":")); row_hash=hashlib.sha256(raw.encode()).hexdigest(); awb=_awb(cleaned)
        debit=_money(_value(cleaned,"debit","debit amount","charge","amount debited","total charge","courier charge","deduction")); credit=_money(_value(cleaned,"credit","credit amount","refund","remittance amount","amount remitted"))
        if document_type=="cod_remittance" and not credit: credit=_money(_value(cleaned,"cod amount","remitted cod","net paid","amount"))
        if document_type=="weight_discrepancy" and not debit: debit=_money(_value(cleaned,"excess charge","difference amount","applied amount","courier charge"))
        if not awb:
            db.add(CourierFinancialUnmatchedRow(id=str(uuid.uuid4()),document_id=doc.id,provider=provider,awb_or_reference=str(_value(cleaned,"order id","order number","reference") or "") or None,amount=debit or credit or None,reason="No AWB/reference column value",source_row_number=number,source_row_hash=row_hash,raw_row=cleaned)); unmatched+=1; continue
        shipment=db.scalar(select(ShiprocketShipment).where(ShiprocketShipment.awb==awb))
        case=db.scalar(select(CourierFinancialCase).where(CourierFinancialCase.provider==provider,CourierFinancialCase.awb==awb))
        if not case:
            case=CourierFinancialCase(id=str(uuid.uuid4()),provider=provider,awb=awb,order_id=shipment.order_id if shipment else None,courier_name=(shipment.courier_name if shipment else None),shipment_status=(shipment.normalized_status if shipment else None),booked_at=(shipment.booked_at if shipment else None),delivered_at=(shipment.delivered_at if shipment else None),declared_weight_g=(shipment.package_weight_kg*1000 if shipment and shipment.package_weight_kg else None),declared_dimensions=({"length_cm":shipment.package_length_cm,"breadth_cm":shipment.package_breadth_cm,"height_cm":shipment.package_height_cm} if shipment else None)); db.add(case)
        entry=CourierFinancialLedgerEntry(id=str(uuid.uuid4()),document_id=doc.id,provider=provider,awb=awb,component=component_for(document_type,cleaned),debit=debit,credit=credit,net_amount=_money(_value(cleaned,"net amount")) or None,tax_amount=_money(_value(cleaned,"tax","gst")) or None,gross_amount=_money(_value(cleaned,"gross amount","total")) or None,provider_reference_id=str(_value(cleaned,"transaction id","reference id","transaction reference") or "") or None,invoice_or_remittance_id=str(_value(cleaned,"invoice id","remittance id","settlement id","remittance number") or "") or None,occurred_at=_date(_value(cleaned,"date","processed date","transaction date","remittance date")),remarks=str(_value(cleaned,"remarks","description","status") or "") or None,source_row_number=number,source_row_hash=row_hash,raw_row=cleaned); db.add(entry); imported+=1
        settlement_id=entry.invoice_or_remittance_id if document_type=="cod_remittance" else None
        if settlement_id and not db.scalar(select(CourierSettlement).where(CourierSettlement.provider==provider,CourierSettlement.settlement_id==settlement_id)):
            db.add(CourierSettlement(id=str(uuid.uuid4()),provider=provider,settlement_id=settlement_id,processed_at=entry.occurred_at,status=str(_value(cleaned,"status") or "") or None,net_paid=credit or None,bank_reference=str(_value(cleaned,"bank transaction id","bank reference") or "") or None,allocations=[{"awb":awb,"amount":credit}],document_id=doc.id))
    db.flush(); rebuild_cases(db); return {"document_id":doc.id,"idempotent":False,"imported":imported,"unmatched":unmatched}

def rebuild_cases(db: Session) -> None:
    now=datetime.now(timezone.utc)
    for case in db.scalars(select(CourierFinancialCase)).all():
        rows=db.scalars(select(CourierFinancialLedgerEntry).where(CourierFinancialLedgerEntry.provider==case.provider,CourierFinancialLedgerEntry.awb==case.awb)).all()
        by=lambda component: sum((r.credit-r.debit) for r in rows if r.component==component)
        case.remitted_cod=max(0,by("cod_remittance")) or None; case.actual_freight=max(0,-by("freight")) or None; case.weight_excess_charge=max(0,-by("weight_excess")) or None
        case.credits_refunds=sum(r.credit for r in rows if r.component=="credit_refund") or None; case.other_debits=sum(r.debit for r in rows if r.component in {"adjustment","rto_freight","cod_fee"}) or None
        issue=None; risk=0.0; summary=None
        duplicate = any(sum(1 for other in rows if other.component == row.component and other.debit == row.debit and other.debit > 0 and other.provider_reference_id == row.provider_reference_id) > 1 for row in rows)
        if duplicate:
            issue="DUPLICATE_DEBIT"; risk=max((r.debit for r in rows), default=0); summary="Repeated imported debit has the same provider reference"
        elif case.expected_cod and case.remitted_cod is not None and case.remitted_cod < case.expected_cod:
            risk=round(case.expected_cod-case.remitted_cod,2); issue="COD_SHORT"; summary=f"COD short by ₹{risk:.2f}"
        elif case.expected_cod and case.action_deadline and case.action_deadline <= now and case.remitted_cod is None:
            risk=round(case.expected_cod,2); issue="COD_OVERDUE"; summary="COD remittance deadline passed without imported remittance evidence"
        elif case.weight_excess_charge:
            issue="WEIGHT_SLAB_JUMP"; risk=case.weight_excess_charge; summary=f"Weight discrepancy charge ₹{risk:.2f}"
        elif case.actual_freight is not None and case.expected_freight is not None and case.actual_freight > case.expected_freight:
            issue="FREIGHT_VARIANCE"; risk=max(0,round(case.actual_freight-case.expected_freight-(case.credits_refunds or 0),2)); summary=f"Freight exceeds expected quote by ₹{risk:.2f}"
        elif any(r.component=="adjustment" and r.debit for r in rows): issue="UNEXPLAINED_ADJUSTMENT"; risk=sum(r.debit for r in rows if r.component=="adjustment"); summary="Imported debit needs classification"
        case.primary_issue_type=issue; case.issue_summary=summary; case.amount_at_risk=risk; case.net_variance=round((case.actual_freight or 0)+(case.weight_excess_charge or 0)+(case.other_debits or 0)-(case.credits_refunds or 0),2)
        age_origin=case.delivered_at or case.booked_at or now
        if age_origin.tzinfo is None: age_origin=age_origin.replace(tzinfo=timezone.utc)
        case.age_days=max(0,(now-age_origin).days); case.priority="Critical" if risk>=5000 else "High" if risk>=1000 else "Medium" if risk>=100 else "Low"
        if not issue: case.os_status="Reconciled"; case.resolved_at=now

def serialize_case(case: CourierFinancialCase, entries=None, actions=None) -> dict:
    data={c.name:getattr(case,c.name) for c in case.__table__.columns}; data["id"]=case.id
    for k,v in list(data.items()):
        if isinstance(v,datetime): data[k]=v.isoformat()
    if entries is not None: data["ledger_entries"]=[{"id":r.id,"component":r.component,"debit":r.debit,"credit":r.credit,"reference":r.provider_reference_id,"invoice_or_remittance_id":r.invoice_or_remittance_id,"date":r.occurred_at.isoformat() if r.occurred_at else None,"remarks":r.remarks,"source_row_number":r.source_row_number,"document_id":r.document_id} for r in entries]
    if actions is not None: data["actions"]=[{"action":a.action,"note":a.note,"actor_name":a.actor_name,"created_at":a.created_at.isoformat() if a.created_at else None} for a in actions]
    return data
