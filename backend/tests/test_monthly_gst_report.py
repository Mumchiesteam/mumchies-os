from decimal import Decimal

from datetime import date

from app.services.monthly_gst_report import (
    HISTORICAL_SHIPPING_ADJUSTMENT,
    JULY_VALIDATED_BASELINE,
    SHOPIFY_SHIPPING_TAX,
    MonthlyGstReportService,
    calculate_monthly_gst_report,
    compare_with_july_baseline,
)


def delivered_order(*, shipping_tax: str | None) -> dict:
    shipping_tax_lines = [] if shipping_tax is None else [{
        "title": "IGST", "ratePercentage": 5,
        "priceSet": {"shopMoney": {"amount": shipping_tax}},
    }]
    total_tax = Decimal("5.00") + Decimal(shipping_tax or "0")
    return {
        "name": "#400001", "createdAt": "2026-08-01T09:00:00+05:30", "cancelledAt": None,
        "displayFinancialStatus": "PAID", "shippingAddress": {"province": "Telangana"},
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "105.00"}},
        "currentShippingPriceSet": {"shopMoney": {"amount": "29.00"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": str(total_tax)}},
        "currentTotalPriceSet": {"shopMoney": {"amount": "134.00"}},
        "shippingLine": {"discountedPriceSet": {"shopMoney": {"amount": "29.00"}}, "taxLines": shipping_tax_lines},
        "lineItems": {"nodes": [{
            "name": "Mumchies product", "taxable": True,
            "taxLines": [{"title": "IGST", "ratePercentage": 5, "priceSet": {"shopMoney": {"amount": "5.00"}}}],
        }]},
        "fulfillments": [{"deliveredAt": "2026-08-10T12:00:00+05:30", "events": {"nodes": []}}],
    }


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


def test_shopify_shipping_tax_is_used_without_a_second_os_adjustment():
    report = calculate_monthly_gst_report([delivered_order(shipping_tax="1.38")], date(2026, 8, 1))
    assert report.summary["total_gst"] == Decimal("6.38")
    assert report.summary["taxable_value"] == Decimal("127.62")
    assert report.adjustments["shopify_shipping_gst"] == Decimal("1.38")
    assert report.adjustments["historical_shipping_gst"] == Decimal("0.00")
    treatment = report.population["shipping_tax_treatments"]["400001"]
    assert treatment == {
        "classification": SHOPIFY_SHIPPING_TAX,
        "shipping_value": Decimal("29.00"),
        "shipping_tax": Decimal("1.38"),
        "taxable_shipping_value": Decimal("27.62"),
    }


def test_historical_shipping_without_shopify_tax_keeps_five_over_105_adjustment():
    report = calculate_monthly_gst_report([delivered_order(shipping_tax=None)], date(2026, 8, 1))
    assert report.summary["total_gst"] == Decimal("6.38")
    assert report.adjustments["shopify_shipping_gst"] == Decimal("0.00")
    assert report.adjustments["historical_shipping_gst"] == Decimal("1.38")
    treatment = report.population["shipping_tax_treatments"]["400001"]
    assert treatment["classification"] == HISTORICAL_SHIPPING_ADJUSTMENT
    assert treatment["shipping_tax"] == Decimal("1.38")
    assert treatment["taxable_shipping_value"] == Decimal("27.62")
