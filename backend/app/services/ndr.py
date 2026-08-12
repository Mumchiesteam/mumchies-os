from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ndr import NDRCase, NDREvent, NDRSyncRun
from app.models.user import User
from app.services.ndr_sources import (
    CourierRow, clean_phone, fetch_delhivery, fetch_shadowfax, fetch_shiprocket,
    fetch_shopify, recommended_action, whatsapp_url,
)
from app.services.ndr_delivery import resolve_if_canonically_delivered


class NDRSyncAlreadyRunning(RuntimeError): pass


def add_event(db: Session, case: NDRCase, event_type: str, description: str, actor: User | None = None, data: dict | None = None) -> None:
    db.add(NDREvent(id=str(uuid4()), case_id=case.id, event_type=event_type, description=description,
        actor_user_id=actor.id if actor else None, actor_name=actor.display_name if actor else "NDR Sync", event_data=data))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _priority(attempts: int, first_ndr: datetime, now: datetime, repeat: bool = False, cod: float = 0) -> str:
    score = int(cod >= 2000) + int(repeat) + int(attempts >= 2) + int(now - _aware(first_ndr) > timedelta(days=2))
    return "high" if score >= 2 else "medium" if score == 1 else "low"


def serialize_case(case: NDRCase, *, events: list[NDREvent] | None = None) -> dict:
    now = datetime.now(timezone.utc); first = _aware(case.first_ndr_at)
    result = {column.name: getattr(case, column.name) for column in case.__table__.columns if column.name != "raw_provider_data"}
    for key, value in list(result.items()):
        if isinstance(value, datetime): result[key] = value.isoformat()
    result["ageing_hours"] = max(int((now-first).total_seconds()//3600),0)
    result["over_sla"] = result["ageing_hours"] > 48 and case.current_status != "resolved"
    # Imported runs carry the exact reason-aware link produced by the proven
    # GitHub automation. Retain the legacy builder only for pre-import rows.
    if not result.get("whatsapp_url"):
        result["whatsapp_url"] = whatsapp_url(case.customer_phone or "", case.customer_name or "", case.failure_reason or "", case.provider_status or "")
    if events is not None:
        result["events"]=[{"id":e.id,"event_type":e.event_type,"description":e.description,"actor_name":e.actor_name,"event_data":e.event_data,"created_at":e.created_at.isoformat() if e.created_at else None} for e in events]
    return result


async def sync_ndr(db: Session, *, trigger: str, actor: User | None = None) -> NDRSyncRun:
    now=datetime.now(timezone.utc); stale=db.scalar(select(NDRSyncRun).where(NDRSyncRun.lock_key=="ndr_sync"))
    if stale and stale.started_at and now-_aware(stale.started_at)>timedelta(minutes=30):
        stale.status="failed"; stale.error="Recovered stale NDR sync lock."; stale.completed_at=now; stale.lock_key=None; db.commit()
    run=NDRSyncRun(id=str(uuid4()),source="shiprocket+shadowfax+delhivery+shopify",trigger=trigger,status="running",lock_key="ndr_sync",started_at=now,actor_user_id=actor.id if actor else None,actor_name=actor.display_name if actor else "Scheduler")
    db.add(run)
    try: db.commit()
    except IntegrityError as error: db.rollback(); raise NDRSyncAlreadyRunning("An NDR sync is already running.") from error
    try:
        shopify, shopify_result = await fetch_shopify()
        shiprocket_result, shadowfax_result = await asyncio.gather(fetch_shiprocket(), fetch_shadowfax())
        delhivery_result = await fetch_delhivery(shopify)
        source_results=[shiprocket_result,shadowfax_result,delhivery_result]

        all_rows=[row for result in source_results for row in result.rows]
        deduped:dict[str,CourierRow]={}; duplicate_count=0; missing_awb=0
        for row in all_rows:
            awb=row.awb.strip()
            if not awb: missing_awb += 1; continue
            if awb in deduped: duplicate_count += 1; continue
            deduped[awb]=row

        phone_counts:dict[str,int]={}
        for record in shopify.values():
            phone=clean_phone(record.phone)
            if phone: phone_counts[phone]=phone_counts.get(phone,0)+1
        phones_matched=0; unmatched_ids=[]; live_by_source={result.name:set() for result in source_results}
        for awb,row in deduped.items():
            live_by_source[row.source].add(awb)
            enrichment=shopify.get(row.order_id.strip().lstrip("#")); phone=clean_phone(row.phone)
            if not phone and enrichment: phone=clean_phone(enrichment.phone)
            name=row.customer_name.strip()
            if (not name or name.casefold() in {"nan","none"}) and enrichment: name=enrichment.name.strip()
            if phone: phones_matched += 1
            elif row.order_id: unmatched_ids.append(row.order_id)
            existing=db.scalar(select(NDRCase).where(NDRCase.awb==awb)); first=existing.first_ndr_at if existing else row.updated_at or now
            values={"order_id":row.order_id or None,"order_number":row.order_id or None,"provider":row.source,"courier_name":row.source.title(),"customer_name":name or None,"customer_phone":phone or None,
                "provider_status":row.status,"failure_reason":row.failure_reason,"recommended_action":recommended_action(row.failure_reason,row.status,phone),"priority":_priority(row.attempts,first,now,phone_counts.get(phone,0)>1),
                "delivery_attempts":row.attempts,"last_provider_update_at":row.updated_at or now,"last_synced_at":now,"raw_provider_data":row.raw}
            if existing:
                changed=existing.provider_status!=row.status or existing.failure_reason!=row.failure_reason
                for key,value in values.items(): setattr(existing,key,value)
                existing.source_lifecycle="resolved" if existing.current_status=="resolved" else "active"
                resolve_if_canonically_delivered(db, existing, now=now)
                if changed: add_event(db,existing,"sync_update",f"{row.source.title()} updated status to {row.status}.",data={"failure_reason":row.failure_reason})
                run.cases_updated += 1
            else:
                existing=NDRCase(id=str(uuid4()),awb=awb,first_ndr_at=first,current_status="new",source_lifecycle="active",products=[],cod_amount=0,**values)
                db.add(existing); db.flush(); add_event(db,existing,"case_created",f"NDR detected from {row.source.title()}.",data={"provider_status":row.status})
                resolve_if_canonically_delivered(db, existing, now=now)
                run.cases_created += 1
            run.cases_seen += 1

        successful_sources={result.name for result in source_results if result.status=="success"}
        for case in db.scalars(select(NDRCase).where(NDRCase.provider.in_(successful_sources))).all():
            if case.awb not in live_by_source.get(case.provider,set()):
                case.source_lifecycle="resolved" if case.current_status=="resolved" else "no_longer_reported"

        shopify_result.details.update({"phones_matched":phones_matched,"phones_total":len(deduped),"phones_missing":len(deduped)-phones_matched,"match_percentage":round(phones_matched*100/len(deduped),1) if deduped else 100.0,"unmatched_order_ids":unmatched_ids[:100]})
        health={result.name:result.health() for result in [*source_results,shopify_result]}
        health["deduplication"]={"status":"success","endpoint":"cross-source AWB","fetched_count":len(all_rows),"accepted_count":len(deduped),"skipped_count":duplicate_count+missing_awb,"duration_ms":0,"error":None,"duplicate_awbs":duplicate_count,"missing_awbs":missing_awb}
        failures=[name for name,item in health.items() if item["status"]=="failed"]
        successes=[name for name,item in health.items() if item["status"]=="success" and name!="deduplication"]
        run.source_health=health; run.status="partial_success" if failures and successes else "failed" if failures else "completed"
        run.error="; ".join(f"{name}: {health[name]['error']}" for name in failures) or None; run.completed_at=datetime.now(timezone.utc); run.lock_key=None; db.commit(); return run
    except Exception as error:
        db.rollback(); failed=db.get(NDRSyncRun,run.id)
        if failed: failed.status="failed"; failed.error=str(error)[:2000]; failed.completed_at=datetime.now(timezone.utc); failed.lock_key=None; db.commit()
        raise
