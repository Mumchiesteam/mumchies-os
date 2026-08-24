from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

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
):
    return (await _report(month, use_cache=not refresh)).payload()


@router.get("/gst/export")
async def export_monthly_gst_report(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    report = await _report(month)
    if report.exceptions:
        raise HTTPException(status_code=409, detail="Resolve GST report exceptions before downloading the filing CSV.")
    filename = f"shopify-{month}-final-gst-b2cs.csv"
    return Response(report.csv_bytes(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
