import asyncio
from decimal import Decimal
from types import SimpleNamespace

from datetime import date, datetime, timezone

from app.services.monthly_gst_report import (
    HISTORICAL_SHIPPING_ADJUSTMENT,
    JULY_VALIDATED_BASELINE,
    SHOPIFY_SHIPPING_TAX,
    MonthlyGstReportService,
    calculate_monthly_gst_report,
    compare_with_july_baseline,
)
from app.services.courier_platform.models import NormalizedShipmentStatus, TrackingResult
from app.services.courier_platform.service import CourierPlatformService


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


def _audit_order(number: str, order_id: str, delivered_at: str | None = None) -> dict:
    value = delivered_order(shipping_tax="1.38")
    value.update({"id": f"gid://shopify/Order/{order_id}", "name": f"#{number}", "fulfillments": [{"deliveredAt": delivered_at, "events": {"nodes": []}}] if delivered_at else []})
    return value


def test_august_uses_delhivery_only_without_shopify_evidence_and_excludes_manual_orders():
    report = calculate_monthly_gst_report(
        [_audit_order("326073", "1", "2026-08-18T09:00:00Z"), _audit_order("325950", "2"), _audit_order("325886", "3"), _audit_order("316161", "4", "2026-08-12T09:00:00Z"), _audit_order("316684", "5", "2026-08-13T09:00:00Z")],
        date(2026, 8, 1),
        {
            "1": {"timestamp": datetime(2026, 8, 18, 10, tzinfo=timezone.utc), "awb": "D-OVERLAP"},
            "2": {"timestamp": datetime(2026, 8, 19, 10, tzinfo=timezone.utc), "awb": "D-ONLY"},
            "3": {"timestamp": datetime(2026, 8, 20, 10, tzinfo=timezone.utc), "awb": "D-SECOND"},
        },
    )
    assert report.summary["delivered_orders"] == 3
    assert report.summary["manual_exclusions"] == 2
    assert report.reconciliation["additional_delhivery_confirmed_deliveries"] == 2
    assert report.reconciliation["overlap_confirmed_by_both"] == 1
    audit = {row["shopify_order_number"]: row for row in report.delivery_audit}
    assert audit["326073"]["delivery_evidence_source"] == "SHOPIFY"
    assert audit["325950"]["delivery_evidence_source"] == "DELHIVERY"
    assert audit["325886"]["awb"] == "D-SECOND"
    assert "316161" not in audit and "316684" not in audit


def test_generic_delhivery_tracking_persists_delivered_timestamp(monkeypatch):
    delivered_at = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    captured = {}
    monkeypatch.setattr("app.services.courier_platform.service.get_shipment", lambda *_: SimpleNamespace(tracking_url=None, provider_order_id="1"))
    monkeypatch.setattr("app.services.courier_platform.service.snapshot", lambda *_: {})
    monkeypatch.setattr("app.services.courier_platform.service.upsert_shipment", lambda _db, _id, **fields: captured.update(fields) or object())
    monkeypatch.setattr("app.services.courier_platform.service.OrderOperationsStore.record_timeline_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.courier_platform.service.append_tracking_events", lambda *args, **kwargs: [])
    class Adapter:
        provider = "delhivery"
        async def track_shipment(self, shipment):
            return TrackingResult(provider="delhivery", status=NormalizedShipmentStatus.DELIVERED, delivered_at=delivered_at)
    asyncio.run(CourierPlatformService().track(object(), order_id="1", adapter=Adapter(), operator="test"))
    assert captured["delivered_at"] == delivered_at
