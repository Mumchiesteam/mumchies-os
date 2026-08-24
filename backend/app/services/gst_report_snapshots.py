from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.gst_report_snapshot import GstReportSnapshot
from app.services.monthly_gst_report import GST_REPORT_METHODOLOGY_VERSION, GstReport


COMPARISON_FIELDS = ("delivered_orders", "taxable_value", "cgst", "sgst", "igst", "total_gst", "gross_sales")


def _json_value(value: object) -> object:
    def convert(item: object) -> object:
        if isinstance(item, Decimal):
            return float(item)
        if isinstance(item, date):
            return item.isoformat()
        raise TypeError(f"Unsupported snapshot value: {type(item).__name__}")
    return json.loads(json.dumps(value, default=convert, sort_keys=True, separators=(",", ":")))


def report_checksum(report: GstReport) -> str:
    payload = json.dumps(_json_value(report.payload()), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload + b"\n" + report.csv_bytes()).hexdigest()


def finalisation_failures(report: GstReport) -> list[str]:
    summary = report.summary
    failures: list[str] = []
    if int(summary["exceptions"]) != 0:
        failures.append("All exceptions must be resolved before finalising.")
    row_orders = sum(int(row["Orders"]) for row in report.rows)
    if row_orders != int(summary["delivered_orders"]):
        failures.append("State-wise order count does not reconcile to delivered orders.")
    row_invoice = sum((Decimal(str(row["Total Invoice Value"])) for row in report.rows), Decimal("0"))
    if row_invoice != Decimal(str(summary["gross_sales"])):
        failures.append("State-wise invoice value does not reconcile to gross sales.")
    if Decimal(str(summary["taxable_value"])) + Decimal(str(summary["total_gst"])) != Decimal(str(summary["gross_sales"])):
        failures.append("Taxable Value + GST does not equal Gross Sales.")
    baseline = report.baseline_comparison
    if baseline is not None and not baseline.get("matches"):
        failures.append("The July validated reconciliation baseline does not match.")
    return failures


def get_final(db: Session, month: str) -> GstReportSnapshot | None:
    return db.scalar(select(GstReportSnapshot).where(GstReportSnapshot.month == month))


def final_payload(snapshot: GstReportSnapshot) -> dict[str, object]:
    payload = dict(snapshot.snapshot)
    payload.update({
        "status": "FINAL",
        "finalised_at": snapshot.finalised_at.isoformat(),
        "methodology_version": snapshot.methodology_version,
        "checksum": snapshot.checksum,
        "can_finalise": False,
        "finalisation_failures": [],
        "comparison_to_final": None,
    })
    return payload


def draft_payload(report: GstReport, final: GstReportSnapshot | None = None) -> dict[str, object]:
    failures = finalisation_failures(report)
    payload = report.payload()
    payload.update({
        "status": "DRAFT",
        "finalised_at": None,
        "methodology_version": GST_REPORT_METHODOLOGY_VERSION,
        "checksum": report_checksum(report),
        "can_finalise": not failures and final is None,
        "finalisation_failures": failures,
        "comparison_to_final": compare_to_final(report, final) if final else None,
        "final_reference": ({"finalised_at": final.finalised_at.isoformat(), "checksum": final.checksum} if final else None),
    })
    return payload


def compare_to_final(report: GstReport, final: GstReportSnapshot) -> dict[str, object]:
    final_summary = final.snapshot["summary"]
    draft_summary = report.summary
    values = {}
    for field in COMPARISON_FIELDS:
        final_value = Decimal(str(final_summary[field]))
        draft_value = Decimal(str(draft_summary[field]))
        values[field] = {"final": final_value, "draft": draft_value, "difference": draft_value - final_value}
    return {"matches": all(value["difference"] == 0 for value in values.values()), "fields": values}


def finalise(db: Session, report: GstReport, expected_checksum: str) -> GstReportSnapshot:
    existing = get_final(db, report.month)
    if existing:
        return existing
    checksum = report_checksum(report)
    if checksum != expected_checksum:
        raise ValueError("The draft changed after it was reviewed. Generate it again before finalising.")
    failures = finalisation_failures(report)
    if failures:
        raise ValueError(" ".join(failures))
    summary = report.summary
    snapshot = GstReportSnapshot(
        month=report.month,
        methodology_version=GST_REPORT_METHODOLOGY_VERSION,
        delivered_order_count=int(summary["delivered_orders"]),
        taxable_value=Decimal(str(summary["taxable_value"])),
        cgst=Decimal(str(summary["cgst"])),
        sgst=Decimal(str(summary["sgst"])),
        igst=Decimal(str(summary["igst"])),
        total_gst=Decimal(str(summary["total_gst"])),
        gross_sales=Decimal(str(summary["gross_sales"])),
        snapshot=_json_value(report.payload()),
        csv_content=report.csv_bytes().decode("utf-8-sig"),
        checksum=checksum,
    )
    db.add(snapshot)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_final(db, report.month)
        if existing:
            return existing
        raise
    db.refresh(snapshot)
    return snapshot
