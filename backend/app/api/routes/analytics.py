from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from app.api.routes.dashboard import IST, _at, _period
from app.services.report_snapshots import ReportSnapshotStore
from app.services.shopify import ShopifyService

router = APIRouter(prefix="/analytics", tags=["analytics"])
_analytics_tasks: dict[str, asyncio.Task[None]] = {}

_INDIA_STATES = {
    "ap": "Andhra Pradesh", "ar": "Arunachal Pradesh", "as": "Assam", "br": "Bihar",
    "cg": "Chhattisgarh", "ch": "Chandigarh", "dl": "Delhi", "ga": "Goa", "gj": "Gujarat",
    "hr": "Haryana", "hp": "Himachal Pradesh", "jh": "Jharkhand", "jk": "Jammu and Kashmir",
    "ka": "Karnataka", "kl": "Kerala", "la": "Ladakh", "ld": "Lakshadweep",
    "mh": "Maharashtra", "mp": "Madhya Pradesh", "mn": "Manipur", "ml": "Meghalaya",
    "mz": "Mizoram", "nl": "Nagaland", "od": "Odisha", "or": "Odisha", "pb": "Punjab",
    "py": "Puducherry", "rj": "Rajasthan", "sk": "Sikkim", "tn": "Tamil Nadu",
    "ts": "Telangana", "tg": "Telangana", "tr": "Tripura", "uk": "Uttarakhand",
    "up": "Uttar Pradesh", "ut": "Uttarakhand", "wb": "West Bengal",
}
_INDIA_STATES.update({value.casefold(): value for value in tuple(_INDIA_STATES.values())})


def _previous_period(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    duration = end - start
    return start - duration, start


def _active(order) -> bool:
    return not order.cancelled_at and str(order.shopify_status or "").casefold() not in {"cancelled", "canceled"}


def _repeat(order) -> bool:
    return (order.customer_orders_count or 0) > 1


def _change(current: float, previous: float, *, points: bool = False) -> dict[str, float | None]:
    return {"absolute": round(current - previous, 2), "percent": None if points or previous == 0 else round((current - previous) * 100 / previous, 1), "points": round(current - previous, 1) if points else None}


def _filter(orders: list, payment: str, customer: str) -> list:
    return [order for order in orders if (payment == "all" or order.payment_type == payment) and (customer == "all" or (_repeat(order) if customer == "repeat" else not _repeat(order)))]


def _state(value: str | None) -> str:
    clean = " ".join(str(value or "").split())
    if not clean: return "Unknown"
    return _INDIA_STATES.get(clean.casefold(), clean.title())


def _place(value: str | None) -> str:
    clean = " ".join(str(value or "").split())
    return clean.title() if clean else "Unknown"


def _pincode(value: str | None) -> str:
    clean = "".join(str(value or "").split())
    return clean or "Unknown"


def _customer_key(order) -> str:
    return str(order.customer_id or order.email or order.phone or order.order_id)


def _geo_metrics(orders: list) -> dict[str, float | int]:
    active = [order for order in orders if _active(order)]
    value = sum(float(order.order_total) for order in active)
    customers = {_customer_key(order) for order in active}
    repeats = [order for order in active if _repeat(order)]
    cod = sum(order.payment_type == "cod" for order in active)
    prepaid = sum(order.payment_type == "prepaid" for order in active)
    return {
        "orders": len(orders), "active_orders": len(active), "order_value": round(value, 2),
        "aov": round(value / len(active), 2) if active else 0, "customers": len(customers),
        "repeat_percent": round(len(repeats) * 100 / len(active), 1) if active else 0,
        "cod_percent": round(cod * 100 / len(active), 1) if active else 0,
        "prepaid_percent": round(prepaid * 100 / len(active), 1) if active else 0,
    }


def _geo_products(current: list, previous: list) -> list[dict]:
    def rows(orders: list) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for order in orders:
            if not _active(order): continue
            for item in order.products:
                key = str(item.sku or item.product_name).casefold()
                row = result.setdefault(key, {"product": item.product_name, "orders": set(), "quantity": 0, "value": 0.0, "repeat_orders": set()})
                row["orders"].add(order.order_id); row["quantity"] += item.quantity
                row["value"] += float(item.price) * item.quantity
                if _repeat(order): row["repeat_orders"].add(order.order_id)
        return result
    now, before = rows(current), rows(previous); total = max(sum(_active(order) for order in current), 1); result = []
    for key, row in now.items():
        old = before.get(key, {}); order_count = len(row["orders"]); old_orders = len(old.get("orders", set()))
        result.append({"product": row["product"], "orders": order_count, "quantity": row["quantity"], "value": round(row["value"], 2), "order_percent": round(order_count * 100 / total, 1), "repeat_orders": len(row["repeat_orders"]), "order_change": order_count - old_orders, "value_change": round(row["value"] - old.get("value", 0), 2)})
    return sorted(result, key=lambda row: (-row["value"], -row["orders"], row["product"]))[:10]


def _geography(current: list, previous: list) -> dict:
    def location(order) -> tuple[str, str, str]:
        address = order.shipping_address
        return (_state(address.state if address else None), _place(address.city if address else None), _pincode(address.pincode if address else None))
    def grouped(orders: list, level: int, parent: tuple[str, ...] = ()) -> dict[str, list]:
        result: dict[str, list] = defaultdict(list)
        for order in orders:
            parts = location(order)
            if parts[:len(parent)] == parent: result[parts[level]].append(order)
        return result
    def table(now_groups: dict[str, list], old_groups: dict[str, list], label: str) -> list[dict]:
        result = []
        for name, orders in now_groups.items():
            now = _geo_metrics(orders); before = _geo_metrics(old_groups.get(name, []))
            result.append({label: name, **now, "orders_change": now["orders"] - before["orders"], "value_change": round(float(now["order_value"]) - float(before["order_value"]), 2), "aov_change": round(float(now["aov"]) - float(before["aov"]), 2), "repeat_points": round(float(now["repeat_percent"]) - float(before["repeat_percent"]), 1)})
        return sorted(result, key=lambda row: (-float(row["order_value"]), str(row[label])))
    current_states, previous_states = grouped(current, 0), grouped(previous, 0)
    states = table(current_states, previous_states, "state"); cities = {}; pincodes = {}; products = {"all": _geo_products(current, previous)}
    for state in current_states:
        now_cities, old_cities = grouped(current, 1, (state,)), grouped(previous, 1, (state,))
        cities[state] = table(now_cities, old_cities, "city")
        products[f"state:{state}"] = _geo_products(current_states[state], previous_states.get(state, []))
        for city in now_cities:
            key = f"{state}|{city}"; now_pins, old_pins = grouped(current, 2, (state, city)), grouped(previous, 2, (state, city))
            pincodes[key] = table(now_pins, old_pins, "pincode")
            products[f"city:{key}"] = _geo_products(now_cities[city], old_cities.get(city, []))
    quality = {"missing_state": 0, "missing_city": 0, "missing_pincode": 0}
    for order in current:
        state, city, pin = location(order)
        quality["missing_state"] += state == "Unknown"; quality["missing_city"] += city == "Unknown"; quality["missing_pincode"] += pin == "Unknown"
    summary, prior = _geo_metrics(current), _geo_metrics(previous)
    comparisons = {key: _change(float(summary[key]), float(prior[key]), points=key.endswith("percent")) for key in summary}
    return {"summary": summary, "comparisons": comparisons, "states": states, "cities": cities, "pincodes": pincodes, "products": products, "data_quality": quality}


def _summary(orders: list) -> dict[str, float | int]:
    active = [order for order in orders if _active(order)]
    repeats = [order for order in active if _repeat(order)]
    value = sum(float(order.order_total) for order in active)
    items = sum(item.quantity for order in orders for item in order.products)
    total = len(orders)
    active_total = len(active)
    fulfilled = sum(str(order.fulfillment_status or "").casefold() == "fulfilled" for order in active)
    return {
        "total_orders": total, "active_orders": active_total, "order_value": round(value, 2),
        "aov": round(value / active_total, 2) if active_total else 0,
        "items_per_order": round(items / total, 2) if total else 0,
        "cancellation_percent": round((total - active_total) * 100 / total, 1) if total else 0,
        "fulfilled_orders": fulfilled,
        "fulfillment_percent": round(fulfilled * 100 / active_total, 1) if active_total else 0,
        "repeat_percent": round(len(repeats) * 100 / active_total, 1) if active_total else 0,
    }


def _payment(orders: list) -> list[dict]:
    result = []
    for key, label in (("cod", "COD"), ("prepaid", "Prepaid"), ("partial_cod", "Partial COD")):
        rows = [order for order in orders if order.payment_type == key]; active = [order for order in rows if _active(order)]
        value = sum(float(order.order_total) for order in active)
        result.append({"key": key, "label": label, "orders": len(active), "percent": round(len(active) * 100 / max(sum(_active(order) for order in orders), 1), 1), "value": round(value, 2), "aov": round(value / len(active), 2) if active else 0, "cancellation_percent": round((len(rows) - len(active)) * 100 / len(rows), 1) if rows else 0})
    return result


def _products(current: list, previous: list) -> list[dict]:
    def aggregate(orders: list) -> dict[str, dict]:
        rows: dict[str, dict] = {}
        for order in orders:
            if not _active(order): continue
            for item in order.products:
                key = str(item.sku or item.product_name).casefold(); row = rows.setdefault(key, {"product": item.product_name, "quantity": 0, "order_ids": set(), "value": 0.0, "new_orders": set(), "repeat_orders": set()})
                row["quantity"] += item.quantity; row["order_ids"].add(order.order_id); row["value"] += float(item.price) * item.quantity; row["repeat_orders" if _repeat(order) else "new_orders"].add(order.order_id)
        return rows
    now, before = aggregate(current), aggregate(previous); total = max(sum(_active(order) for order in current), 1); result = []
    for key, row in now.items():
        old = before.get(key, {}); orders = len(row["order_ids"])
        result.append({"product": row["product"], "quantity": row["quantity"], "orders": orders, "value": round(row["value"], 2), "order_percent": round(orders * 100 / total, 1), "new_orders": len(row["new_orders"]), "repeat_orders": len(row["repeat_orders"]), "quantity_change": row["quantity"] - old.get("quantity", 0), "order_change": orders - len(old.get("order_ids", set())), "value_change": round(row["value"] - old.get("value", 0), 2)})
    return sorted(result, key=lambda row: (-row["quantity"], -row["value"], row["product"]))[:10]


def _trend(orders: list, start: datetime, end: datetime) -> dict:
    hours = (end - start).total_seconds() / 3600; granularity = "hour" if hours <= 48 else "week" if (end - start).days > 62 else "day"; buckets = defaultdict(lambda: {"orders": 0, "revenue": 0.0})
    for order in orders:
        if not _active(order): continue
        created = _at(order.created_date)
        if not created: continue
        if granularity == "hour": key = created.astimezone(IST).strftime("%Y-%m-%d %H:00")
        elif granularity == "week": key = f"{created.date().isocalendar().year}-W{created.date().isocalendar().week:02d}"
        else: key = created.date().isoformat()
        buckets[key]["orders"] += 1; buckets[key]["revenue"] += float(order.order_total)
    return {"granularity": granularity, "points": [{"label": key, "orders": value["orders"], "revenue": round(value["revenue"], 2)} for key, value in sorted(buckets.items())]}


async def _build(start: datetime, end: datetime, preset: str, label: str, payment: str, customer: str) -> dict:
    previous_start, previous_end = _previous_period(start, end)
    orders = await ShopifyService().get_orders_created_between(previous_start, end)
    current = _filter([order for order in orders if (created := _at(order.created_date)) and start <= created < end], payment, customer)
    previous = _filter([order for order in orders if (created := _at(order.created_date)) and previous_start <= created < previous_end], payment, customer)
    now, before = _summary(current), _summary(previous)
    comparisons = {key: _change(float(now[key]), float(before[key]), points=key.endswith("percent")) for key in now}
    active = [order for order in current if _active(order)]; repeats = [order for order in active if _repeat(order)]; new = [order for order in active if not _repeat(order)]
    customer_data = {"new_customers": len({order.customer_id or order.email or order.phone or order.order_id for order in new}), "repeat_customers": len({order.customer_id or order.email or order.phone or order.order_id for order in repeats}), "new_revenue": round(sum(float(order.order_total) for order in new), 2), "repeat_revenue": round(sum(float(order.order_total) for order in repeats), 2), "new_aov": round(sum(float(order.order_total) for order in new) / len(new), 2) if new else 0, "repeat_aov": round(sum(float(order.order_total) for order in repeats) / len(repeats), 2) if repeats else 0}
    return {"period": {"preset": preset, "start": start.date().isoformat(), "end": (end - timedelta(days=1)).date().isoformat(), "label": label}, "filters": {"payment": payment, "customer": customer}, "business": now, "comparisons": comparisons, "customers": customer_data, "payment": _payment(current), "products": _products(current, previous), "trend": _trend(current, start, end), "geography": _geography(current, previous)}


def _key(preset: str, start: datetime, end: datetime, payment: str, customer: str) -> str: return f"analytics:v3:{preset}:{start.date()}:{end.date()}:{payment}:{customer}"

async def _refresh(key: str, start: datetime, end: datetime, preset: str, label: str, payment: str, customer: str) -> None:
    try: ReportSnapshotStore.save_success(key, await _build(start, end, preset, label, payment, customer))
    except Exception as error: ReportSnapshotStore.save_error(key, f"{type(error).__name__}: {str(error)[:250]}")
    finally: _analytics_tasks.pop(key, None)

def start_analytics_refresh(key: str, start: datetime, end: datetime, preset: str, label: str, payment: str = "all", customer: str = "all") -> bool:
    if key in _analytics_tasks and not _analytics_tasks[key].done(): return False
    _analytics_tasks[key] = asyncio.create_task(_refresh(key, start, end, preset, label, payment, customer)); return True

@router.get("")
async def analytics(preset: str = Query("last_30_days"), start: date | None = None, end: date | None = None, payment: str = "all", customer: str = "all", refresh: bool = False) -> dict:
    start_at, end_at, label = _period(preset, start, end); key = _key(preset, start_at, end_at, payment, customer); snapshot = ReportSnapshotStore.get(key)
    if refresh or ReportSnapshotStore.is_stale(snapshot, 900): start_analytics_refresh(key, start_at, end_at, preset, label, payment, customer)
    if not snapshot or not isinstance(snapshot.get("data"), dict): raise HTTPException(503, "Analytics is preparing this period. Try again shortly.")
    return {**snapshot["data"], "last_refreshed_at": snapshot.get("last_refreshed_at"), "refresh_error": snapshot.get("refresh_error"), "refreshing": key in _analytics_tasks}
