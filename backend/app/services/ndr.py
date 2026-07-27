from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ndr import NDRCase, NDREvent, NDRSyncRun
from app.models.user import User
from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport
from app.services.shopify import ShopifyService
from app.services.shiprocket import ShiprocketService


class NDRSyncAlreadyRunning(RuntimeError): pass


def add_event(db: Session, case: NDRCase, event_type: str, description: str, actor: User | None = None, data: dict | None = None) -> None:
    db.add(NDREvent(id=str(uuid4()), case_id=case.id, event_type=event_type, description=description, actor_user_id=actor.id if actor else None, actor_name=actor.display_name if actor else "NDR Sync", event_data=data))


def _priority(cod: float, repeat: bool, attempts: int, first_ndr: datetime, now: datetime) -> str:
    if first_ndr.tzinfo is None: first_ndr = first_ndr.replace(tzinfo=timezone.utc)
    score = int(cod >= 2000) + int(repeat) + int(attempts >= 2) + int(now - first_ndr > timedelta(days=2))
    return "high" if score >= 2 else "medium" if score == 1 else "low"


def _recommended(reason: str, attempts: int) -> str:
    text = reason.casefold()
    if "address" in text or "location" in text: return "Verify address and share delivery landmark"
    if "refus" in text or "cancel" in text: return "Call customer before requesting reattempt"
    if "unavailable" in text or "not reachable" in text: return "Call or WhatsApp customer and schedule reattempt"
    if attempts >= 2: return "Escalate to courier and confirm final reattempt"
    return "Contact customer and courier for reattempt"


def serialize_case(case: NDRCase, *, events: list[NDREvent] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    first = case.first_ndr_at if case.first_ndr_at.tzinfo else case.first_ndr_at.replace(tzinfo=timezone.utc)
    result = {column.name: getattr(case, column.name) for column in case.__table__.columns if column.name != "raw_provider_data"}
    for key, value in list(result.items()):
        if isinstance(value, datetime): result[key] = value.isoformat()
    result["ageing_hours"] = max(int((now - first).total_seconds() // 3600), 0)
    result["over_sla"] = result["ageing_hours"] > 48 and case.current_status != "resolved"
    if events is not None:
        result["events"] = [{"id": e.id, "event_type": e.event_type, "description": e.description, "actor_name": e.actor_name, "event_data": e.event_data, "created_at": e.created_at.isoformat() if e.created_at else None} for e in events]
    return result


async def sync_ndr(db: Session, *, trigger: str, actor: User | None = None) -> NDRSyncRun:
    now = datetime.now(timezone.utc)
    stale = db.scalar(select(NDRSyncRun).where(NDRSyncRun.lock_key == "ndr_sync"))
    if stale and stale.started_at:
        started = stale.started_at if stale.started_at.tzinfo else stale.started_at.replace(tzinfo=timezone.utc)
        if now - started > timedelta(minutes=30):
            stale.status = "failed"; stale.error = "Recovered stale NDR sync lock."; stale.completed_at = now; stale.lock_key = None; db.commit()
    run = NDRSyncRun(id=str(uuid4()), source="shiprocket+shadowfax+shopify", trigger=trigger, status="running", lock_key="ndr_sync", started_at=now, actor_user_id=actor.id if actor else None, actor_name=actor.display_name if actor else "Scheduler")
    db.add(run)
    try: db.commit()
    except IntegrityError as error:
        db.rollback(); raise NDRSyncAlreadyRunning("An NDR sync is already running.") from error
    try:
        source_health: dict[str, dict] = {}

        async def source(name: str, operation) -> list:
            started = time.monotonic()
            try:
                rows = await operation()
                source_health[name] = {"status": "success", "rows_fetched": len(rows), "error": None, "duration_ms": int((time.monotonic() - started) * 1000)}
                return rows
            except Exception as error:
                source_health[name] = {"status": "failed", "rows_fetched": 0, "error": str(error)[:1000], "duration_ms": int((time.monotonic() - started) * 1000)}
                return []

        shiprocket_rows = await source("shiprocket", ShiprocketService().list_ndr_shipments)
        async def fetch_shadowfax() -> list[dict]:
            if not settings.shadowfax_token or not settings.shadowfax_base_url:
                raise RuntimeError("Shadowfax API credentials are not configured.")
            transport = ShadowfaxHTTPTransport(token=settings.shadowfax_token, base_url=settings.shadowfax_base_url)
            return await transport.list_ndr_shipments()

        shadowfax_rows = await source("shadowfax", fetch_shadowfax)
        shopify_orders = await source("shopify", ShopifyService().get_orders_for_ndr_enrichment)

        by_id = {str(o.order_id): o for o in shopify_orders}
        by_number = {str(o.order_number).lstrip("#"): o for o in shopify_orders}
        by_awb = {str(o.external_tracking.awb): o for o in shopify_orders if o.external_tracking and o.external_tracking.awb}
        phone_counts: dict[str, int] = {}
        for order in shopify_orders:
            phone = "".join(c for c in str(order.phone or "") if c.isdigit())[-10:]
            if phone: phone_counts[phone] = phone_counts.get(phone, 0) + 1
        provider_rows = [("shiprocket", row) for row in shiprocket_rows] + [("shadowfax", row) for row in shadowfax_rows]
        for provider, raw in provider_rows:
            shipment = raw.get("shipment") if isinstance(raw.get("shipment"), dict) else {}
            order_data = raw.get("order") if isinstance(raw.get("order"), dict) else {}
            awb = str(raw.get("awb") or raw.get("awb_code") or raw.get("awb_number") or shipment.get("awb") or shipment.get("awb_code") or "").strip()
            if not awb: continue
            existing = db.scalar(select(NDRCase).where(NDRCase.awb == awb))
            provider_status = str(raw.get("status") or raw.get("current_status") or raw.get("status_display") or shipment.get("status") or "NDR")
            reason = str(raw.get("ndr_reason") or raw.get("failure_reason") or raw.get("reason") or raw.get("remarks") or raw.get("ndr_remarks") or "Delivery attempt failed")
            attempt_value = raw.get("ndr_attempt") or raw.get("attempt_count") or raw.get("attempt_number") or 1
            try: attempts = max(int(attempt_value), 1)
            except (TypeError, ValueError): attempts = 1
            tracking_url = raw.get("tracking_url") or raw.get("customer_track_url") or shipment.get("tracking_url")
            provider_time = _parse_datetime(raw.get("ndr_date") or raw.get("updated_at") or raw.get("updated") or raw.get("created_at")) or now
            order_reference = str(raw.get("channel_order_id") or raw.get("order_id") or raw.get("client_order_id") or order_data.get("id") or "")
            order = by_awb.get(awb) or by_id.get(order_reference) or by_number.get(order_reference.lstrip("#"))
            first_ndr = existing.first_ndr_at if existing else provider_time
            phone = str(order.phone or "") if order else None
            repeat = bool(phone and phone_counts.get("".join(c for c in phone if c.isdigit())[-10:], 0) > 1)
            cod = float(order.cod_collectable_amount if order else Decimal("0"))
            values = {
                "order_id": str(order.order_id) if order else order_reference or None, "order_number": order.order_number if order else order_reference or None,
                "provider": provider, "courier_name": str(raw.get("courier_name") or raw.get("courier") or shipment.get("courier_name") or provider.title()), "customer_name": order.customer_name if order else None,
                "customer_phone": phone, "customer_address": order.shipping_address.model_dump() if order and order.shipping_address else None,
                "products": [p.model_dump(mode="json") for p in order.products] if order else [], "cod_amount": cod,
                "shopify_order_url": f"https://{settings.shopify_store}/admin/orders/{order.order_id}" if order and settings.shopify_store else None,
                "provider_tracking_url": tracking_url, "provider_status": provider_status, "failure_reason": reason,
                "recommended_action": _recommended(reason, attempts), "priority": _priority(cod, repeat, attempts, first_ndr, now),
                "delivery_attempts": attempts, "last_provider_update_at": provider_time, "last_synced_at": now, "raw_provider_data": raw,
            }
            if existing:
                changed = existing.provider_status != provider_status or existing.failure_reason != reason
                for key, value in values.items(): setattr(existing, key, value)
                if changed: add_event(db, existing, "sync_update", f"Courier updated status to {provider_status}.", data={"failure_reason": reason})
                run.cases_updated += 1
            else:
                existing = NDRCase(id=str(uuid4()), awb=awb, first_ndr_at=first_ndr, current_status="new", **values)
                db.add(existing); db.flush(); add_event(db, existing, "case_created", f"NDR detected from {provider.title()}.", data={"provider_status": provider_status})
                run.cases_created += 1
            run.cases_seen += 1
        failures = [name for name, health in source_health.items() if health["status"] == "failed"]
        successes = [name for name, health in source_health.items() if health["status"] == "success"]
        run.source_health = source_health
        if successes:
            run.status = "partial_success" if failures else "completed"
            run.error = "; ".join(f"{name}: {source_health[name]['error']}" for name in failures) or None
        else:
            run.status = "failed"
            run.error = "; ".join(f"{name}: {source_health[name]['error']}" for name in failures)
        run.completed_at = datetime.now(timezone.utc); run.lock_key = None; db.commit(); return run
    except Exception as error:
        db.rollback()
        failed = db.get(NDRSyncRun, run.id)
        if failed:
            failed.status = "failed"; failed.error = str(error)[:2000]; failed.completed_at = datetime.now(timezone.utc); failed.lock_key = None; db.commit()
        raise


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None
