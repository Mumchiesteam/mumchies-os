from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.orders import (
    _call_outcome_is_on_hold, _call_outcome_requires_follow_up, _is_fresh_order,
    _load_orders,
)
from app.db.session import SessionLocal, get_db
from app.models.ndr import NDRCase, NDREvent
from app.services.order_operations import OrderOperationsStore
from app.services.report_snapshots import ReportSnapshotStore
from app.services.shopify import ShopifyService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
IST = ZoneInfo("Asia/Kolkata")
OPERATORS = ("Ajit", "Rupesh")
MEANINGFUL_ORDER_ACTIONS = {
    "call_logged", "address_corrected", "address_verified", "address_confirmation_commented",
    "package_details_saved", "order_cancelled", "shipment_booked", "courier_booked",
    "courier_booking_reconciled", "shadowfax_manual_shipment_recorded",
    "WhatsApp opened for COD confirmation",
}
MEANINGFUL_NDR_ACTIONS = {"add_note", "assign", "customer_contacted", "courier_contacted", "resolve", "reopen"}
_dashboard_refresh_tasks: dict[str, asyncio.Task[None]] = {}


def _period(preset: str, start: date | None, end: date | None, now: datetime | None = None) -> tuple[datetime, datetime, str]:
    local_now = (now or datetime.now(timezone.utc)).astimezone(IST)
    today = local_now.date()
    if preset == "today": first = last = today
    elif preset == "yesterday": first = last = today - timedelta(days=1)
    elif preset == "last_7_days": first, last = today - timedelta(days=6), today
    elif preset == "this_month": first, last = today.replace(day=1), today
    elif preset == "custom":
        if not start or not end or end < start: raise HTTPException(422, "Select a valid custom date range.")
        if (end - start).days > 365: raise HTTPException(422, "Dashboard date range cannot exceed 366 days.")
        first, last = start, end
    else: raise HTTPException(422, "Unsupported dashboard period.")
    start_at = datetime.combine(first, time.min, tzinfo=IST).astimezone(timezone.utc)
    end_at = datetime.combine(last + timedelta(days=1), time.min, tzinfo=IST).astimezone(timezone.utc)
    return start_at, end_at, f"{first.isoformat()} to {last.isoformat()}"


def _at(value: object) -> datetime | None:
    if not value: return None
    if isinstance(value, datetime): return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError: return None


def _operator(value: object) -> str | None:
    text = str(value or "").strip().casefold()
    return next((name for name in OPERATORS if name.casefold() in text), None)


def _order_activity(operations: dict[str, dict], start: datetime, end: datetime) -> dict[str, set[str]]:
    result = {name: set() for name in OPERATORS}
    for order_id, record in operations.items():
        events = [*(record.get("human_actions") or []), *(record.get("timeline_events") or [])]
        for event in events:
            if str(event.get("action") or "") not in MEANINGFUL_ORDER_ACTIONS: continue
            occurred = _at(event.get("timestamp")); actor = _operator(event.get("operator"))
            if actor and occurred and start <= occurred < end: result[actor].add(str(order_id))
    return result


def _all_actioned_order_ids(operations: dict[str, dict]) -> set[str]:
    return {
        str(order_id) for order_id, record in operations.items()
        if any(str(event.get("action") or "") in MEANINGFUL_ORDER_ACTIONS for event in [*(record.get("human_actions") or []), *(record.get("timeline_events") or [])])
    }


def _ndr_activity(events: list[NDREvent], start: datetime, end: datetime) -> dict[str, set[str]]:
    result = {name: set() for name in OPERATORS}
    for event in events:
        actor = _operator(event.actor_name); occurred = _at(event.created_at)
        if actor and event.event_type in MEANINGFUL_NDR_ACTIONS and occurred and start <= occurred < end:
            result[actor].add(str(event.case_id))
    return result


def _business_metrics(orders: list, actioned_ids: set[str]) -> dict[str, object]:
    active = [order for order in orders if not order.cancelled_at and str(order.shopify_status or "").casefold() not in {"cancelled", "canceled"}]
    payment = {key: [order for order in active if order.payment_type == key] for key in ("cod", "prepaid", "partial_cod")}
    repeat = sum((order.customer_orders_count or 0) > 1 for order in active)
    processed = sum(
        order.order_id in actioned_ids or str(order.fulfillment_status or "").casefold() in {"fulfilled", "partial", "partially_fulfilled"}
        for order in active
    )
    products: dict[str, dict[str, float | int | str]] = {}
    for order in active:
        for item in order.products:
            key = str(item.sku or item.product_name).casefold()
            row = products.setdefault(key, {"product": item.product_name, "quantity": 0, "orders": 0, "order_value": 0.0, "_ids": set()})
            row["quantity"] += item.quantity
            row["order_value"] += float(item.price) * item.quantity
            row["_ids"].add(order.order_id)
    top = []
    for row in products.values():
        row["orders"] = len(row.pop("_ids"))
        top.append(row)
    top.sort(key=lambda value: (-int(value["quantity"]), -float(value["order_value"]), str(value["product"])))
    total = len(active)
    return {
        "orders": {"total": total, "value": sum(float(order.order_total) for order in active),
                   "repeat_percent": round(repeat * 100 / total, 1) if total else 0.0,
                   "actioned": processed, "pending": total - processed, "cancelled_excluded": len(orders) - total},
        "payment_mix": {key: {"count": len(values), "percent": round(len(values) * 100 / total, 1) if total else 0.0} for key, values in payment.items()},
        "top_products": top[:10],
    }


async def _build_dashboard(preset: str, start_at: datetime, end_at: datetime, label: str, db: Session) -> dict[str, object]:
    operations = OrderOperationsStore.all()
    order_activity = _order_activity(operations, start_at, end_at)
    ndr_events = db.scalars(select(NDREvent).where(NDREvent.created_at >= start_at, NDREvent.created_at < end_at)).all()
    ndr_activity = _ndr_activity(list(ndr_events), start_at, end_at)
    operational = await _load_orders(db)
    # Today, yesterday and last-seven-day views are already fully covered by the canonical
    # 15-day operational read. Reuse it instead of issuing a second Shopify request.
    if start_at >= datetime.now(timezone.utc) - timedelta(days=14):
        business_orders = [order for order in operational if (created := _at(order.created_date)) and start_at <= created < end_at]
    else:
        business_orders = await ShopifyService().get_orders_created_between(start_at, end_at)
    business = _business_metrics(business_orders, _all_actioned_order_ids(operations))

    ndr_cases = db.scalars(select(NDRCase)).all()
    now = datetime.now(timezone.utc)
    active_ndr = [case for case in ndr_cases if case.source_lifecycle == "active" and case.current_status != "resolved"]
    needs = {
        "fresh": sum(_is_fresh_order(order) for order in operational),
        "follow_up": sum(_call_outcome_requires_follow_up(order) for order in operational),
        "on_hold": sum(_call_outcome_is_on_hold(order) for order in operational),
        "ready_booking": sum(str(order.operational_status or "").casefold() == "ready for booking" for order in operational),
        "active_ndr": len(active_ndr),
        "ndr_over_sla": sum((now - (_at(case.first_ndr_at) or now)).total_seconds() > 172800 for case in active_ndr),
        # The canonical reconciliation endpoint performs historical Shopify and Shiprocket
        # reads. It is deliberately not nested in the Dashboard request: doing so duplicated
        # that expensive provider workflow when App also loaded Reconciliation on startup.
        "reconciliation_exceptions": None,
    }
    team = []
    for name in OPERATORS:
        team.append({"operator": name, "orders_actioned": len(order_activity[name]), "ndrs_actioned": len(ndr_activity[name])})
    return {
        "period": {"preset": preset, "start": start_at.astimezone(IST).date().isoformat(), "end": (end_at.astimezone(IST).date() - timedelta(days=1)).isoformat(), "label": label},
        "needs_attention": needs,
        "team_activity": {"operators": team, "total": {"orders_actioned": len(set().union(*order_activity.values())), "ndrs_actioned": len(set().union(*ndr_activity.values()))}},
        **business,
    }


def _dashboard_key(preset: str, start_at: datetime, end_at: datetime) -> str:
    return f"dashboard:{preset}:{start_at.date().isoformat()}:{end_at.date().isoformat()}"


async def _refresh_dashboard_snapshot(key: str, preset: str, start_at: datetime, end_at: datetime, label: str) -> None:
    try:
        with SessionLocal() as db:
            result = await _build_dashboard(preset, start_at, end_at, label, db)
        ReportSnapshotStore.save_success(key, result)
    except Exception:  # noqa: BLE001 - a stale snapshot is safer than blanking the Dashboard
        ReportSnapshotStore.save_error(key, "Dashboard refresh failed. The last successful data is still available.")
    finally:
        _dashboard_refresh_tasks.pop(key, None)


def _start_dashboard_refresh(key: str, preset: str, start_at: datetime, end_at: datetime, label: str) -> bool:
    task = _dashboard_refresh_tasks.get(key)
    if task and not task.done():
        return False
    _dashboard_refresh_tasks[key] = asyncio.create_task(_refresh_dashboard_snapshot(key, preset, start_at, end_at, label))
    return True


@router.get("")
async def dashboard(
    preset: str = Query("today"), start: date | None = None, end: date | None = None,
    refresh: bool = False,
) -> dict[str, object]:
    start_at, end_at, label = _period(preset, start, end)
    key = _dashboard_key(preset, start_at, end_at)
    snapshot = ReportSnapshotStore.get(key)
    if refresh or ReportSnapshotStore.is_stale(snapshot, 300):
        _start_dashboard_refresh(key, preset, start_at, end_at, label)
    if not snapshot or not isinstance(snapshot.get("data"), dict):
        raise HTTPException(status_code=503, detail="Dashboard is preparing this period. Try again shortly.")
    return {
        **snapshot["data"],
        "last_refreshed_at": snapshot.get("last_refreshed_at"),
        "refresh_error": snapshot.get("refresh_error"),
        "refreshing": bool(_dashboard_refresh_tasks.get(key) and not _dashboard_refresh_tasks[key].done()),
    }
