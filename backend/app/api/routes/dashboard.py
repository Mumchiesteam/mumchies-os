from __future__ import annotations

import asyncio
import logging
import traceback
from pathlib import Path
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.orders import (
    _load_orders, _operational_queue_partition,
)
from app.db.session import SessionLocal, get_db
from app.models.ndr import NDRCase, NDREvent
from app.models.user import User
from app.services.ndr_delivery import resolve_active_terminal_cases
from app.services.ndr_eligibility import is_ndr_eligible
from app.services.order_operations import OrderOperationsStore
from app.services.report_snapshots import ReportSnapshotStore
from app.services.shopify import ShopifyService
from app.services.runtime_metrics import background_job

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
IST = ZoneInfo("Asia/Kolkata")
# Team Activity -> Orders is deliberately narrower than general operator activity: only a
# timestamped event proving that the order reached a confirmed provider shipment belongs here.
# Preparatory work remains visible in the order audit trail but must not inflate shipped orders.
SUCCESSFUL_SHIPMENT_ACTIONS = {
    "shipment_booked", "courier_booked", "courier_booking_reconciled",
    "shadowfax_manual_shipment_recorded", "shadowfax_direct_test_324663_booked",
}
MEANINGFUL_ORDER_ACTIONS = {
    "call_logged", "address_corrected", "address_verified", "address_confirmation_commented",
    "package_details_saved", "order_cancelled", "shipment_booked", "courier_booked",
    "courier_booking_reconciled", "shadowfax_manual_shipment_recorded",
    "WhatsApp opened for COD confirmation",
}
MEANINGFUL_NDR_ACTIONS = {"add_note", "assign", "customer_contacted", "courier_contacted", "resolve", "reopen"}
_dashboard_refresh_tasks: dict[str, asyncio.Task[None]] = {}
logger = logging.getLogger(__name__)


def _period(preset: str, start: date | None, end: date | None, now: datetime | None = None) -> tuple[datetime, datetime, str]:
    local_now = (now or datetime.now(timezone.utc)).astimezone(IST)
    today = local_now.date()
    if preset == "today": first = last = today
    elif preset == "yesterday": first = last = today - timedelta(days=1)
    elif preset == "last_7_days": first, last = today - timedelta(days=6), today
    elif preset in {"this_month", "month_to_date"}: first, last = today.replace(day=1), today
    elif preset == "last_30_days": first, last = today - timedelta(days=29), today
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
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError: return None


def _operator(value: object, operators: dict[str, str]) -> str | None:
    return operators.get(str(value or "").strip().casefold())


def _active_operator_roster(users: list[User]) -> tuple[list[str], dict[str, str]]:
    roster = sorted({user.display_name.strip() for user in users if user.is_active and user.display_name.strip()}, key=str.casefold)
    identities = {
        alias.strip().casefold(): user.display_name.strip()
        for user in users
        if user.is_active and user.display_name.strip()
        for alias in (user.display_name, user.username)
        if alias and alias.strip()
    }
    return roster, identities


def _order_activity(operations: dict[str, dict], start: datetime, end: datetime, operators: dict[str, str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for order_id, record in operations.items():
        events = [*(record.get("human_actions") or []), *(record.get("timeline_events") or [])]
        for event in events:
            if str(event.get("action") or "") not in SUCCESSFUL_SHIPMENT_ACTIONS: continue
            occurred = _at(event.get("timestamp")); actor = _operator(event.get("operator"), operators)
            if actor and occurred and start <= occurred < end: result[actor].add(str(order_id))
    return result


def _all_actioned_order_ids(operations: dict[str, dict]) -> set[str]:
    return {
        str(order_id) for order_id, record in operations.items()
        if any(str(event.get("action") or "") in MEANINGFUL_ORDER_ACTIONS for event in [*(record.get("human_actions") or []), *(record.get("timeline_events") or [])])
    }


def _ndr_activity(events: list[NDREvent], start: datetime, end: datetime, operators: dict[str, str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for event in events:
        actor = _operator(event.actor_name, operators); occurred = _at(event.created_at)
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
    users = list(db.scalars(select(User).where(User.is_active.is_(True))).all())
    roster, operators = _active_operator_roster(users)
    order_activity = _order_activity(operations, start_at, end_at, operators)
    ndr_events = db.scalars(select(NDREvent).where(NDREvent.created_at >= start_at, NDREvent.created_at < end_at)).all()
    ndr_activity = _ndr_activity(list(ndr_events), start_at, end_at, operators)
    operational = await _load_orders(db)
    queues = _operational_queue_partition(operational)
    # Today, yesterday and last-seven-day views are already fully covered by the canonical
    # 15-day operational read. Reuse it instead of issuing a second Shopify request.
    if start_at >= datetime.now(timezone.utc) - timedelta(days=14):
        business_orders = [order for order in operational if (created := _at(order.created_date)) and start_at <= created < end_at]
    else:
        business_orders = await ShopifyService().get_orders_created_between(start_at, end_at)
    business = _business_metrics(business_orders, _all_actioned_order_ids(operations))

    resolve_active_terminal_cases(db)
    ndr_cases = db.scalars(select(NDRCase)).all()
    now = datetime.now(timezone.utc)
    active_ndr = [case for case in ndr_cases if case.source_lifecycle == "active" and case.current_status != "resolved" and is_ndr_eligible(case.provider_status, case.failure_reason)]
    needs = {
        "fresh": len(queues["fresh"]),
        "follow_up": len(queues["follow_up"]),
        "on_hold": len(queues["on_hold"]),
        # A labelled subset of the canonical Operations population, not an additive queue.
        "ready_booking": sum(str(order.operational_status or "").casefold() == "ready for booking" for order in queues["operations"]),
        "active_ndr": len(active_ndr),
        "ndr_over_sla": sum((now - (_at(case.first_ndr_at) or now)).total_seconds() > 172800 for case in active_ndr),
        # The canonical reconciliation endpoint performs historical Shopify and Shiprocket
        # reads. It is deliberately not nested in the Dashboard request: doing so duplicated
        # that expensive provider workflow when App also loaded Reconciliation on startup.
        "reconciliation_exceptions": None,
    }
    team = [
        {"operator": name, "orders_actioned": len(order_activity[name]), "ndrs_actioned": len(ndr_activity[name])}
        for name in roster
    ]
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
        async with background_job("dashboard_refresh", heavy=True):
            with SessionLocal() as db:
                result = await _build_dashboard(preset, start_at, end_at, label, db)
        ReportSnapshotStore.save_success(key, result)
    except Exception as error:  # noqa: BLE001 - a stale snapshot is safer than blanking the Dashboard
        logger.exception("Dashboard snapshot refresh failed")
        message = str(error).strip()[:300]
        locations = " > ".join(f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in traceback.extract_tb(error.__traceback__)[-3:])
        detail = f"{type(error).__name__}: {message}" if message else type(error).__name__
        ReportSnapshotStore.save_error(key, f"{detail} [{locations}]")
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
