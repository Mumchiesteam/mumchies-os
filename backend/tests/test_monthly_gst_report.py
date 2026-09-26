import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.courier_platform.models import NormalizedShipmentStatus, TrackingResult
from app.services.courier_platform.service import CourierPlatformService
from app.services.monthly_gst_report import JULY_VALIDATED_BASELINE, MonthlyGstReportService, calculate_monthly_gst_report, compare_with_july_baseline


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


def _order(number: str, order_id: str, delivered_at: str | None = None) -> dict:
    return {
        "id": f"gid://shopify/Order/{order_id}", "name": f"#{number}", "createdAt": "2026-07-20T10:00:00Z",
        "cancelledAt": None, "displayFinancialStatus": "PAID", "shippingAddress": {"province": "Karnataka"},
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "100.00"}},
        "currentShippingPriceSet": {"shopMoney": {"amount": "0.00"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "4.76"}},
        "currentTotalPriceSet": {"shopMoney": {"amount": "100.00"}},
        "lineItems": {"nodes": []},
        "fulfillments": [{"deliveredAt": delivered_at, "events": {"nodes": []}}] if delivered_at else [],
    }


def test_august_uses_delhivery_only_when_shopify_has_no_delivery_evidence():
    shopify = _order("326073", "1", "2026-08-18T09:00:00Z")
    delhivery = _order("325950", "2")
    delhivery_second = _order("325886", "3")
    manual = _order("316161", "4", "2026-08-12T09:00:00Z")
    manual_second = _order("316684", "5", "2026-08-13T09:00:00Z")
    report = calculate_monthly_gst_report(
        [shopify, delhivery, delhivery_second, manual, manual_second], date(2026, 8, 1),
        {
            "1": {"timestamp": datetime(2026, 8, 18, 10, tzinfo=timezone.utc), "awb": "D-OVERLAP"},
            "2": {"timestamp": datetime(2026, 8, 19, 10, tzinfo=timezone.utc), "awb": "D-ONLY"},
            "3": {"timestamp": datetime(2026, 8, 20, 10, tzinfo=timezone.utc), "awb": "D-SECOND"},
        },
    )
    assert report.summary["delivered_orders"] == 3
    assert report.summary["manual_exclusions"] == 2
    assert report.reconciliation["shopify_confirmed_deliveries"] == 3
    assert report.reconciliation["additional_delhivery_confirmed_deliveries"] == 2
    assert report.reconciliation["overlap_confirmed_by_both"] == 1
    assert {row["shopify_order_number"] for row in report.delivery_audit} == {"326073", "325950", "325886"}
    assert next(row for row in report.delivery_audit if row["shopify_order_number"] == "326073")["delivery_evidence_source"] == "SHOPIFY"
    assert next(row for row in report.delivery_audit if row["shopify_order_number"] == "325950")["awb"] == "D-ONLY"
    assert next(row for row in report.delivery_audit if row["shopify_order_number"] == "325886")["delivery_evidence_source"] == "DELHIVERY"


def test_generic_delhivery_tracking_persists_delivered_timestamp(monkeypatch):
    delivered_at = datetime(2026, 8, 20, 10, tzinfo=timezone.utc)
    captured = {}
    monkeypatch.setattr("app.services.courier_platform.service.get_shipment", lambda *_: SimpleNamespace(tracking_url=None))
    monkeypatch.setattr("app.services.courier_platform.service.snapshot", lambda *_: {})
    monkeypatch.setattr("app.services.courier_platform.service.upsert_shipment", lambda _db, _id, **fields: captured.update(fields) or object())
    monkeypatch.setattr("app.services.courier_platform.service.OrderOperationsStore.record_timeline_event", lambda *args, **kwargs: None)

    class Adapter:
        provider = "delhivery"
        async def track_shipment(self, shipment):
            return TrackingResult(provider="delhivery", status=NormalizedShipmentStatus.DELIVERED, delivered_at=delivered_at)

    asyncio.run(CourierPlatformService().track(object(), order_id="1", adapter=Adapter(), operator="test"))
    assert captured["delivered_at"] == delivered_at
