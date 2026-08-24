from decimal import Decimal

from app.services.monthly_gst_report import JULY_VALIDATED_BASELINE, MonthlyGstReportService, compare_with_july_baseline


def test_monthly_report_cache_is_one_hour():
    assert MonthlyGstReportService._cache_ttl_seconds == 3600


def test_july_validated_baseline_is_locked():
    summary = {
        "delivered_orders": 2659, "taxable_value": Decimal("1420171.32"),
        "cgst": Decimal("2467.85"), "sgst": Decimal("2467.85"), "igst": Decimal("66070.68"),
        "total_gst": Decimal("71006.38"), "gross_sales": Decimal("1491177.70"),
    }
    result = compare_with_july_baseline(summary)
    assert result["matches"] is True
    assert all(value == 0 for value in result["differences"].values())
    assert JULY_VALIDATED_BASELINE["orders"] == Decimal("2659")


def test_july_regression_reports_a_difference():
    result = compare_with_july_baseline({
        "delivered_orders": 2658, "taxable_value": Decimal("1420171.32"),
        "cgst": Decimal("2467.85"), "sgst": Decimal("2467.85"), "igst": Decimal("66070.68"),
        "total_gst": Decimal("71006.38"), "gross_sales": Decimal("1491177.70"),
    })
    assert result["matches"] is False
    assert result["differences"]["orders"] == Decimal("-1")
