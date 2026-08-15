"""Read-only comparison of Shopify, provider and OS address provenance.

Usage: PYTHONPATH=. python -u scripts/cross_order_address_audit.py 324695 324578
No provider or Shopify mutation methods are imported or called.
"""
from __future__ import annotations

import asyncio
import sys

from app.services.delhivery import DelhiveryService
from app.services.order_operations import OrderOperationsStore
from app.services.shopify import ShopifyService


async def main(numbers: list[str]) -> None:
    orders = await ShopifyService().get_latest_orders(force_refresh=True)
    by_number = {order.order_number.lstrip("#"): order for order in orders}
    compact = []
    for number in numbers:
        order = by_number.get(number.lstrip("#"))
        if not order or not order.external_tracking or not order.external_tracking.awb:
            compact.append({"order": number, "classification": "insufficient evidence"})
            continue
        try:
            provider = await DelhiveryService().label_data(order.external_tracking.awb)
        except Exception:
            compact.append({"order": number, "awb": order.external_tracking.awb, "classification": "insufficient evidence"})
            continue
        shop = order.shipping_address
        ops = OrderOperationsStore.get(order.order_id)
        provenance = ops.get("address_provenance") if isinstance(ops.get("address_provenance"), dict) else None
        shop_pin, provider_pin = str(shop.pincode or "") if shop else "", str(provider.get("pin") or "")
        shop_name = str(shop.name or order.customer_name or "") if shop else str(order.customer_name or "")
        provider_name = str(provider.get("name") or "")
        other_match = next((candidate.order_number for candidate in orders if candidate.order_id != order.order_id and candidate.shipping_address and str(candidate.shipping_address.pincode or "") == provider_pin and str(candidate.shipping_address.name or "").casefold() == provider_name.casefold()), None)
        if other_match:
            classification = "confirmed cross-order"
        elif shop_pin == provider_pin:
            classification = "legitimate correction" if provenance else "insufficient evidence"
        else:
            classification = "suspicious" if provenance else "insufficient evidence"
        compact.append({
            "order": order.order_number, "awb": order.external_tracking.awb,
            "shopify": {"customer": shop_name[:3] + "…" if shop_name else None, "city": shop.city if shop else None, "pincode": shop_pin},
            "provider": {"customer": provider_name[:3] + "…" if provider_name else None, "city": provider.get("city"), "pincode": provider_pin},
            "provenance": None if not provenance else {key: provenance.get(key) for key in ("order_id", "order_number", "source", "saved_at", "operator", "revision")},
            "matched_other_order": other_match, "classification": classification,
        })
    for row in compact:
        print(row)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
