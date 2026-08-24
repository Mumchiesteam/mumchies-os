from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.gst_report_snapshots import draft_payload, final_payload, finalise, get_final
from app.services.monthly_gst_report import MonthlyGstReportService
from app.services.shopify import ShopifyConfigurationError, ShopifySyncError


router = APIRouter(prefix="/reports", tags=["reports"])


def _month(value: str) -> date:
    try:
        parsed = date.fromisoformat(f"{value}-01")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Month must use YYYY-MM format.") from error
    if parsed > date.today().replace(day=1):
        raise HTTPException(status_code=422, detail="Future months cannot be reported.")
    return parsed


async def _report(month: str, *, use_cache: bool = True):
    try:
        return await MonthlyGstReportService().generate(_month(month), use_cache=use_cache)
    except ShopifyConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (ShopifySyncError, httpx.HTTPError) as error:
        raise HTTPException(status_code=502, detail="Unable to retrieve the Shopify GST report.") from error


@router.get("/gst")
async def monthly_gst_report(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    refresh: bool = Query(False, description="Bypass the report cache and reload Shopify data."),
    regenerate: bool = Query(False, description="Create a new draft without changing an existing final report."),
    db: Session = Depends(get_db),
):
    parsed = _month(month)
    saved = get_final(db, month)
    if saved and not regenerate:
        if refresh:
            raise HTTPException(status_code=409, detail="This month is finalised. Use Regenerate Draft to compare current Shopify data without replacing the final report.")
        return final_payload(saved)
    report = await _report(month, use_cache=not refresh and not regenerate)
    return draft_payload(report, saved)


@router.get("/gst/final")
async def saved_monthly_gst_report(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), db: Session = Depends(get_db)):
    _month(month)
    saved = get_final(db, month)
    return {"exists": bool(saved), "report": final_payload(saved) if saved else None}


class FinalisePayload(BaseModel):
    month: str
    checksum: str


@router.post("/gst/finalise")
async def finalise_monthly_gst_report(payload: FinalisePayload, db: Session = Depends(get_db)):
    parsed = _month(payload.month)
    saved = get_final(db, payload.month)
    if saved:
        return final_payload(saved)
    report = MonthlyGstReportService.cached(parsed)
    if report is None:
        raise HTTPException(status_code=409, detail="The reviewed draft is no longer cached. Generate it again before finalising.")
    try:
        return final_payload(finalise(db, report, payload.checksum))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/gst/export")
async def export_monthly_gst_report(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), db: Session = Depends(get_db)):
    _month(month)
    saved = get_final(db, month)
    if saved:
        filename = f"shopify-{month}-final-gst-b2cs.csv"
        return Response(saved.csv_content.encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    report = await _report(month)
    if report.exceptions:
        raise HTTPException(status_code=409, detail="Resolve GST report exceptions before downloading the filing CSV.")
    filename = f"shopify-{month}-final-gst-b2cs.csv"
    return Response(report.csv_bytes(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
