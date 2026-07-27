from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ndr import NDRCase, NDREvent, NDRSyncRun
from app.models.shiprocket import ShiprocketShipment
from app.models.user import User
from app.services.courier_platform.base import ProviderError
from app.services.courier_platform.registry import courier_registry
from app.services.shopify import ShopifyService


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
        try: shopify_orders = await ShopifyService().get_latest_orders(force_refresh=True)
        except Exception: shopify_orders = []
        by_id = {o.order_id: o for o in shopify_orders}
        by_awb = {o.external_tracking.awb: o for o in shopify_orders if o.external_tracking and o.external_tracking.awb}
        phone_counts: dict[str, int] = {}
        for order in shopify_orders:
            phone = "".join(c for c in str(order.phone or "") if c.isdigit())[-10:]
            if phone: phone_counts[phone] = phone_counts.get(phone, 0) + 1
        shipments = list(db.scalars(select(ShiprocketShipment).where(ShiprocketShipment.awb.is_not(None))).all())
        known_awbs = {str(s.awb) for s in shipments}
        for order in shopify_orders:
            external = order.external_tracking
            provider = str(external.provider or "").casefold() if external else ""
            if external and external.awb and external.awb not in known_awbs and provider in {"shiprocket", "shadowfax"}:
                shipments.append(SimpleNamespace(order_id=order.order_id, provider=provider, awb=external.awb, courier_name=external.provider, normalized_status=external.status, latest_status=external.status, ndr_reason=None, ndr_remarks=None, ndr_attempt=None, tracking_url=external.tracking_url, latest_tracking_at=None, provider_order_id=order.order_number))
        for shipment in shipments:
            awb = str(shipment.awb or "").strip()
            if not awb: continue
            existing = db.scalar(select(NDRCase).where(NDRCase.awb == awb))
            provider = (shipment.provider or "shiprocket").casefold()
            provider_status = shipment.latest_status or shipment.normalized_status or ""
            reason = shipment.ndr_reason or shipment.ndr_remarks or "Delivery attempt failed"
            attempts = max(int(shipment.ndr_attempt or 1), 1)
            tracking_url = shipment.tracking_url
            raw: dict | list | None = None
            provider_time = shipment.latest_tracking_at or now
            try:
                tracked = await courier_registry.get(provider).track_shipment({"awb": awb, "provider_order_id": shipment.provider_order_id, "normalized_status": shipment.normalized_status, "latest_status": shipment.latest_status})
                provider_status = tracked.provider_status or tracked.status.value
                reason = tracked.ndr_reason or tracked.courier_remarks or reason
                attempts = max(int(tracked.ndr_attempt or attempts), attempts)
                tracking_url = tracked.tracking_url or tracking_url
                provider_time = tracked.latest_tracking_at or now
                raw = tracked.raw_response
                is_ndr = tracked.status.value == "ndr" or "ndr" in f"{provider_status} {reason}".casefold() or "undeliver" in f"{provider_status} {reason}".casefold()
            except ProviderError:
                is_ndr = bool(shipment.ndr_reason or shipment.normalized_status == "ndr" or existing)
            if not is_ndr and not existing: continue
            order = by_id.get(shipment.order_id) or by_awb.get(awb)
            first_ndr = existing.first_ndr_at if existing else provider_time
            phone = str(order.phone or "") if order else None
            repeat = bool(phone and phone_counts.get("".join(c for c in phone if c.isdigit())[-10:], 0) > 1)
            cod = float(order.cod_collectable_amount if order else Decimal("0"))
            values = {
                "order_id": shipment.order_id, "order_number": order.order_number if order else shipment.provider_order_id,
                "provider": provider, "courier_name": shipment.courier_name or provider.title(), "customer_name": order.customer_name if order else None,
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
        run.status = "completed"; run.completed_at = datetime.now(timezone.utc); run.lock_key = None; db.commit(); return run
    except Exception as error:
        db.rollback()
        failed = db.get(NDRSyncRun, run.id)
        if failed:
            failed.status = "failed"; failed.error = str(error)[:2000]; failed.completed_at = datetime.now(timezone.utc); failed.lock_key = None; db.commit()
        raise
