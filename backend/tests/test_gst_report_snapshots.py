from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.gst_report_snapshot import GstReportSnapshot
from app.services.gst_report_snapshots import compare_to_final, final_payload, finalisation_failures, finalise, report_checksum
from app.services.monthly_gst_report import GstReport


def july_report(*, orders: int = 2659, exceptions: int = 0) -> GstReport:
    summary = {
        "delivered_orders": orders, "raw_delivered_orders": 2663, "excluded_orders": 4,
        "gross_sales": Decimal("1491177.70"), "taxable_value": Decimal("1420171.32"),
        "cgst": Decimal("2467.85"), "sgst": Decimal("2467.85"), "igst": Decimal("66070.68"),
        "total_gst": Decimal("71006.38"), "exceptions": exceptions,
    }
    rows = [{
        "Place of Supply": "All states", "GST Rate": "5%", "Orders": orders,
        "Taxable Value": Decimal("1420171.32"), "CGST": Decimal("2467.85"),
        "SGST": Decimal("2467.85"), "IGST": Decimal("66070.68"),
        "Total Invoice Value": Decimal("1491177.70"),
    }]
    return GstReport(
        "2026-07", summary, rows,
        ([{"order_number": "1", "reason": "Review", "invoice_value": Decimal("1"), "delivered_date": date(2026, 7, 1).isoformat()}] if exceptions else []),
        {"previous_month_created_delivered": {"orders": 1, "value": Decimal("500")}, "selected_month_created_delivered_following": {"orders": 2, "value": Decimal("1000")}},
        {"original_shopify_gst": Decimal("68939.25"), "shipping_gst": Decimal("2067.13"), "product_gst_corrections": Decimal("0")},
        {"matches": orders == 2659, "differences": {}},
        {"raw_delivered_order_numbers": ["1"], "filing_eligible_order_numbers": ["1"], "excluded_order_numbers": []},
    )


def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_validated_july_report_can_be_finalised_and_reloaded_without_shopify():
    db = session()
    report = july_report()
    original_csv = report.csv_bytes()
    saved = finalise(db, report, report_checksum(report))
    db.expire_all()
    reloaded = db.scalar(select(GstReportSnapshot).where(GstReportSnapshot.month == "2026-07"))
    assert reloaded is not None
    assert final_payload(reloaded)["status"] == "FINAL"
    assert reloaded.csv_content.encode("utf-8-sig") == original_csv
    assert reloaded.snapshot["population"]["filing_eligible_order_numbers"] == ["1"]
    assert reloaded.checksum == saved.checksum


def test_final_is_immutable_and_regenerated_draft_only_compares():
    db = session()
    final = finalise(db, july_report(), report_checksum(july_report()))
    changed = july_report(orders=2658)
    comparison = compare_to_final(changed, final)
    assert comparison["matches"] is False
    assert comparison["fields"]["delivered_orders"]["difference"] == Decimal("-1")
    assert db.scalar(select(GstReportSnapshot)).delivered_order_count == 2659


def test_finalisation_requires_zero_exceptions_and_full_reconciliation():
    report = july_report(exceptions=1)
    failures = finalisation_failures(report)
    assert "All exceptions must be resolved before finalising." in failures
    assert finalisation_failures(july_report()) == []


def test_saved_month_route_does_not_query_shopify(monkeypatch):
    import asyncio
    from app.api.routes import reports as routes

    db = session()
    report = july_report()
    finalise(db, report, report_checksum(report))

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("Shopify must not be called for a saved month")

    monkeypatch.setattr(routes, "_report", unexpected)
    payload = asyncio.run(routes.monthly_gst_report(month="2026-07", refresh=False, regenerate=False, db=db))
    assert payload["status"] == "FINAL"
    assert payload["summary"]["delivered_orders"] == 2659
