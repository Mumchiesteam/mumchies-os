from __future__ import annotations

import csv
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from io import StringIO
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.shiprocket import ShiprocketShipment
from app.services.delhivery import DelhiveryError, DelhiveryService
from app.services.shopify import ShopifyService


INDIA = ZoneInfo("Asia/Kolkata")
CENT = Decimal("0.01")
CSV_HEADERS = ["Place of Supply", "GST Rate", "Orders", "Taxable Value", "CGST", "SGST", "IGST", "Total Invoice Value"]
FILING_EXCLUSIONS = {"REFUNDED", "PARTIALLY_REFUNDED", "VOIDED"}
JULY_VALIDATED_BASELINE = {
    "orders": Decimal("2659"), "taxable_value": Decimal("1420171.32"),
    "cgst": Decimal("2467.85"), "sgst": Decimal("2467.85"),
    "igst": Decimal("66070.68"), "total_gst": Decimal("71006.38"),
    "gross_sales": Decimal("1491177.70"),
}
MANUAL_PLACE_OF_SUPPLY = {"322131": "Bihar", "319899": "Punjab"}
JULY_FORCE_FIVE_PERCENT = {"320055", "320839", "321243", "320959", "319899"}
# Temporary, reviewed correction: these May deliveries were marked delivered in Shopify in
# August. Keep this month-specific until the historical records are corrected at source.
AUGUST_2026_MANUAL_DELIVERY_EXCLUSIONS = {"316161", "316684"}


def _decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _money(order: dict, field: str) -> Decimal:
    return _decimal(order[field]["shopMoney"]["amount"])


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _local_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(INDIA).date()


def _month_after(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def _month_before(value: date) -> date:
    return date(value.year - (value.month == 1), 12 if value.month == 1 else value.month - 1, 1)


def _delivery_timestamp(order: dict) -> str | None:
    values: list[str] = []
    for fulfillment in order.get("fulfillments") or []:
        if fulfillment.get("deliveredAt"):
            values.append(fulfillment["deliveredAt"])
        values.extend(
            event["happenedAt"] for event in ((fulfillment.get("events") or {}).get("nodes") or [])
            if event.get("status") == "DELIVERED" and event.get("happenedAt")
        )
    return max(values, key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))) if values else None


def _shopify_order_id(order: dict) -> str:
    return str(order.get("id") or "").rsplit("/", 1)[-1]


def _line_rate(line: dict) -> Decimal | None:
    tax_lines = [value for value in line.get("taxLines") or [] if _decimal(value["priceSet"]["shopMoney"]["amount"])]
    if not tax_lines:
        return None
    cgst = {_decimal(value.get("ratePercentage")) for value in tax_lines if "CGST" in str(value.get("title")).upper()}
    sgst = {_decimal(value.get("ratePercentage")) for value in tax_lines if "SGST" in str(value.get("title")).upper()}
    if cgst and sgst and len(cgst) == 1 and cgst == sgst:
        return next(iter(cgst)) * 2
    rates = {_decimal(value.get("ratePercentage")) for value in tax_lines}
    return next(iter(rates)) if len(rates) == 1 else None


@dataclass(frozen=True)
class GstReport:
    month: str
    summary: dict[str, object]
    rows: list[dict[str, object]]
    exceptions: list[dict[str, object]]
    reconciliation: dict[str, object]
    adjustments: dict[str, object]
    baseline_comparison: dict[str, object] | None
    delivery_audit: list[dict[str, object]]

    def payload(self) -> dict[str, object]:
        return {
            "month": self.month, "summary": self.summary, "rows": self.rows,
            "exceptions": self.exceptions, "reconciliation": self.reconciliation,
            "adjustments": self.adjustments, "baseline_comparison": self.baseline_comparison,
            "delivery_audit": self.delivery_audit,
        }

    def csv_bytes(self) -> bytes:
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows({key: row[key] for key in CSV_HEADERS} for row in self.rows)
        writer.writerows({
            "Place of Supply": f"EXCEPTION - Order {value['order_number']}: {value['reason']}",
            "GST Rate": "REVIEW", "Orders": 1, "Taxable Value": "", "CGST": "", "SGST": "", "IGST": "",
            "Total Invoice Value": value["invoice_value"],
        } for value in self.exceptions)
        return output.getvalue().encode("utf-8-sig")


class MonthlyGstReportService:
    _cache: dict[str, tuple[float, GstReport]] = {}
    _cache_ttl_seconds = 3600
    _query = """query MonthlyGstOrders($first:Int!,$after:String,$query:String!){
      orders(first:$first,after:$after,query:$query,sortKey:UPDATED_AT){
          nodes{id name createdAt cancelledAt displayFinancialStatus shippingAddress{province}
          currentSubtotalPriceSet{shopMoney{amount}} currentShippingPriceSet{shopMoney{amount}}
          currentTotalTaxSet{shopMoney{amount}} currentTotalPriceSet{shopMoney{amount}}
          lineItems(first:100){nodes{name taxable taxLines{title ratePercentage priceSet{shopMoney{amount}}}}}
          fulfillments(first:50){deliveredAt events(first:50){nodes{status happenedAt}}}}
        pageInfo{hasNextPage endCursor}}
    }"""

    def __init__(self, shopify: ShopifyService | None = None, db: Session | None = None) -> None:
        self.shopify = shopify or ShopifyService()
        self.db = db

    async def generate(self, month: date, *, use_cache: bool = True) -> GstReport:
        month = month.replace(day=1)
        cache_key = month.strftime("%Y-%m")
        cached = self._cache.get(cache_key)
        if use_cache and cached and cached[0] > time.time():
            return cached[1]
        orders = await self._fetch_orders(month)
        delhivery_evidence = await self._delhivery_evidence(orders)
        report = calculate_monthly_gst_report(orders, month, delhivery_evidence)
        self._cache[cache_key] = (time.time() + self._cache_ttl_seconds, report)
        return report

    async def _delhivery_evidence(self, orders: list[dict]) -> dict[str, dict[str, object]]:
        """Read actual delivery evidence only for OS-known Delhivery Shopify shipments.

        This does not persist or infer dates. A tracking failure simply leaves the order to
        the existing Shopify-only path.
        """
        if self.db is None:
            return {}
        order_ids = {_shopify_order_id(order) for order in orders}
        rows = self.db.execute(select(ShiprocketShipment.order_id, ShiprocketShipment.awb).where(
            ShiprocketShipment.provider == "delhivery",
            ShiprocketShipment.awb.is_not(None),
        )).all()
        evidence: dict[str, dict[str, object]] = {}
        service = DelhiveryService()
        for order_id, awb in rows:
            if order_id not in order_ids or not awb:
                continue
            try:
                tracked = await service.tracking(awb)
            except (DelhiveryError, httpx.HTTPError):
                continue
            timestamp = tracked.get("delivered_at")
            if str(tracked.get("status") or "").casefold() != "delivered" or not isinstance(timestamp, datetime):
                continue
            evidence[order_id] = {"timestamp": timestamp, "awb": awb}
        return evidence

    async def _fetch_orders(self, month: date) -> list[dict]:
        after: str | None = None
        values: list[dict] = []
        activity_start = datetime(month.year, month.month, 1, tzinfo=INDIA).isoformat()
        while True:
            data = await self.shopify.graphql(self._query, {
                "first": 250, "after": after, "query": f"updated_at:>='{activity_start}'",
            })
            connection = data["orders"]
            values.extend(connection.get("nodes") or [])
            page_info = connection["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            after = page_info["endCursor"]
        return list({str(value["name"]).lstrip("#"): value for value in values}.values())


def calculate_monthly_gst_report(
    orders: list[dict], month: date, delhivery_evidence: dict[str, dict[str, object]] | None = None,
) -> GstReport:
    month = month.replace(day=1)
    next_month = _month_after(month)
    previous_month = _month_before(month)
    delhivery_evidence = delhivery_evidence or {}
    delivered: list[tuple[dict, date, str, str | None]] = []
    following_deliveries: list[dict] = []
    for order in orders:
        timestamp = _delivery_timestamp(order)
        source = "SHOPIFY"
        awb: str | None = None
        if timestamp:
            delivered_date = _local_date(timestamp)
            awb = str((delhivery_evidence.get(_shopify_order_id(order)) or {}).get("awb") or "") or None
        else:
            delhivery = delhivery_evidence.get(_shopify_order_id(order))
            if not delhivery or not isinstance(delhivery.get("timestamp"), datetime):
                continue
            delivered_date = delhivery["timestamp"].astimezone(INDIA).date()
            source = "DELHIVERY"
            awb = str(delhivery.get("awb") or "") or None
        created_date = _local_date(order["createdAt"])
        if month <= delivered_date < next_month:
            delivered.append((order, delivered_date, source, awb))
        if month <= created_date < next_month and next_month <= delivered_date < _month_after(next_month):
            following_deliveries.append(order)
    raw_count = len(delivered)
    manual_exclusions = [item for item in delivered if month == date(2026, 8, 1) and str(item[0]["name"]).lstrip("#") in AUGUST_2026_MANUAL_DELIVERY_EXCLUSIONS]
    excluded = [item for item in delivered if item[0].get("cancelledAt") or item[0].get("displayFinancialStatus") in FILING_EXCLUSIONS]
    eligible = [item for item in delivered if item not in excluded and item not in manual_exclusions]
    groups: dict[tuple[str, Decimal], dict[str, object]] = defaultdict(lambda: {
        "orders": 0, "taxable": Decimal("0"), "tax": Decimal("0"), "invoice": Decimal("0"),
    })
    exceptions: list[dict[str, object]] = []
    original_gst = shipping_gst = product_corrections = Decimal("0")
    delivery_audit: list[dict[str, object]] = []
    for order, delivered_date, source, awb in eligible:
        number = str(order["name"]).lstrip("#")
        state = MANUAL_PLACE_OF_SUPPLY.get(number, str((order.get("shippingAddress") or {}).get("province") or "").strip())
        subtotal = _money(order, "currentSubtotalPriceSet")
        shipping = _money(order, "currentShippingPriceSet")
        original_tax = _money(order, "currentTotalTaxSet")
        invoice = _money(order, "currentTotalPriceSet")
        delivery_audit.append({
            "shopify_order_number": number, "invoice_value": _round(invoice),
            "delivery_date": delivered_date.isoformat(), "delivery_evidence_source": source,
            "awb": awb,
        })
        original_gst += original_tax
        rates = {rate for line in order["lineItems"]["nodes"] if (rate := _line_rate(line)) is not None}
        if number in JULY_FORCE_FIVE_PERCENT or any("FINGER MILLET (RAGI)" in str(line["name"]).upper() for line in order["lineItems"]["nodes"]):
            rates.add(Decimal("5"))
        if not rates:
            rates = {Decimal("5")}
        if not state:
            exceptions.append({"order_number": number, "reason": "Place of supply missing", "invoice_value": _round(invoice), "delivered_date": delivered_date.isoformat()})
            continue
        if len(rates) != 1:
            exceptions.append({"order_number": number, "reason": "Multiple product GST rates; shipping allocation requires review", "invoice_value": _round(invoice), "delivered_date": delivered_date.isoformat()})
            continue
        rate = next(iter(rates))
        if rate != Decimal("5") and shipping:
            exceptions.append({"order_number": number, "reason": f"Shipping allocation requires review for {rate}% supply", "invoice_value": _round(invoice), "delivered_date": delivered_date.isoformat()})
            continue
        missing_tax_lines = [line for line in order["lineItems"]["nodes"] if _line_rate(line) is None]
        product_tax = original_tax
        if number in JULY_FORCE_FIVE_PERCENT:
            product_tax = _round(subtotal * Decimal("5") / Decimal("105"))
        elif missing_tax_lines:
            expected = _round(subtotal * rate / (Decimal("100") + rate))
            taxable_from_tax = original_tax / (rate / Decimal("100")) if original_tax and rate else Decimal("0")
            residual = (subtotal - original_tax) - taxable_from_tax
            if original_tax == 0 or abs(residual) > Decimal("1"):
                product_tax = expected
        product_corrections += product_tax - original_tax
        order_shipping_gst = _round(shipping * Decimal("5") / Decimal("105")) if shipping else Decimal("0")
        shipping_gst += order_shipping_gst
        final_tax = product_tax + order_shipping_gst
        bucket = groups[(state, rate)]
        bucket["orders"] += 1
        bucket["taxable"] += invoice - final_tax
        bucket["tax"] += final_tax
        bucket["invoice"] += invoice
    rows: list[dict[str, object]] = []
    cgst = sgst = igst = taxable = gross = Decimal("0")
    for (state, rate), bucket in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        tax = _round(bucket["tax"])
        if state.casefold() == settings.gst_origin_state.casefold():
            row_cgst = _round(tax / 2)
            row_sgst = tax - row_cgst
            row_igst = Decimal("0")
        else:
            row_cgst = row_sgst = Decimal("0")
            row_igst = tax
        row = {
            "Place of Supply": state, "GST Rate": f"{rate.normalize()}%", "Orders": bucket["orders"],
            "Taxable Value": _round(bucket["taxable"]), "CGST": row_cgst, "SGST": row_sgst,
            "IGST": row_igst, "Total Invoice Value": _round(bucket["invoice"]),
        }
        rows.append(row)
        taxable += row["Taxable Value"]
        cgst += row_cgst
        sgst += row_sgst
        igst += row_igst
        gross += row["Total Invoice Value"]
    previous_created = [order for order, _, _, _ in eligible if previous_month <= _local_date(order["createdAt"]) < month]
    shopify_confirmed = sum(1 for _, _, source, _ in delivered if source == "SHOPIFY")
    delhivery_confirmed = sum(1 for _, _, source, _ in delivered if source == "DELHIVERY")
    overlap_confirmed = sum(
        1 for order, delivered_date, source, _ in delivered
        if source == "SHOPIFY"
        and (evidence := delhivery_evidence.get(_shopify_order_id(order)))
        and isinstance(evidence.get("timestamp"), datetime)
        and month <= evidence["timestamp"].astimezone(INDIA).date() < next_month
    )
    summary = {
        "delivered_orders": len(eligible), "raw_delivered_orders": raw_count, "excluded_orders": len(excluded),
        "manual_exclusions": len(manual_exclusions),
        "gross_sales": _round(sum((_money(order, "currentTotalPriceSet") for order, _, _, _ in eligible), Decimal("0"))),
        "taxable_value": _round(taxable), "cgst": _round(cgst), "sgst": _round(sgst), "igst": _round(igst),
        "total_gst": _round(cgst + sgst + igst), "exceptions": len(exceptions),
    }
    reconciliation = {
        "previous_month_created_delivered": {"orders": len(previous_created), "value": _round(sum((_money(order, "currentTotalPriceSet") for order in previous_created), Decimal("0")))},
        "selected_month_created_delivered_following": {"orders": len(following_deliveries), "value": _round(sum((_money(order, "currentTotalPriceSet") for order in following_deliveries), Decimal("0")))},
        "shopify_confirmed_deliveries": shopify_confirmed,
        "additional_delhivery_confirmed_deliveries": delhivery_confirmed,
        "overlap_confirmed_by_both": overlap_confirmed,
        "excluded_cancelled_refunded": len(excluded),
        "manual_exclusions": len(manual_exclusions),
        "final_unique_gst_order_count": len(eligible),
    }
    adjustments = {"original_shopify_gst": _round(original_gst), "shipping_gst": _round(shipping_gst), "product_gst_corrections": _round(product_corrections)}
    baseline = compare_with_july_baseline(summary) if month == date(2026, 7, 1) else None
    return GstReport(month.strftime("%Y-%m"), summary, rows, exceptions, reconciliation, adjustments, baseline, delivery_audit)


def compare_with_july_baseline(summary: dict[str, object]) -> dict[str, object]:
    actual = {
        "orders": Decimal(str(summary["delivered_orders"])), "taxable_value": Decimal(str(summary["taxable_value"])),
        "cgst": Decimal(str(summary["cgst"])), "sgst": Decimal(str(summary["sgst"])), "igst": Decimal(str(summary["igst"])),
        "total_gst": Decimal(str(summary["total_gst"])), "gross_sales": Decimal(str(summary["gross_sales"])),
    }
    differences = {key: actual[key] - expected for key, expected in JULY_VALIDATED_BASELINE.items()}
    return {"matches": all(value == 0 for value in differences.values()), "differences": differences}
