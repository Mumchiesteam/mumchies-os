from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.services.ndr_eligibility import is_ndr_eligible, is_pre_pickup_state
from app.services.shopify import ShopifyService


@dataclass(slots=True)
class CourierRow:
    source: str
    order_id: str
    awb: str
    customer_name: str = ""
    phone: str = ""
    city: str = ""
    status: str = ""
    failure_reason: str = ""
    attempts: int = 0
    updated_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ShopifyRecord:
    phone: str = ""
    name: str = ""
    created: datetime | None = None


@dataclass(slots=True)
class SourceResult:
    name: str
    endpoint: str
    rows: list[Any]
    status: str = "success"
    fetched: int = 0
    accepted: int = 0
    skipped: int = 0
    error: str | None = None
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def health(self) -> dict[str, Any]:
        return {"status": self.status, "endpoint": self.endpoint, "fetched_count": self.fetched,
                "accepted_count": self.accepted, "skipped_count": self.skipped,
                "duration_ms": self.duration_ms, "error": self.error, **self.details}


def clean_phone(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.casefold() in {"not authorized", "nan", "none", "null"}:
        return ""
    digits = re.sub(r"\D", "", text).lstrip("0")
    if len(digits) == 10:
        digits = "91" + digits
    return digits if len(digits) == 12 and digits.startswith("91") else ""


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, text[:19]):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def recommended_action(reason: str, status: str, phone: str) -> str:
    reason_l, status_u, valid = reason.casefold(), status.upper(), bool(clean_phone(phone))
    if "OUT FOR DELIVERY" in status_u: return "OFD today - nudge customer"
    if "wrong address" in reason_l or "address" in reason_l: return "Nudge to accept (likely fake attempt)"
    if "future delivery" in reason_l: return "Nudge to accept next attempt"
    if "uncontactable" in reason_l or "not available" in reason_l: return "Call customer" if valid else "No phone - check Shopify"
    if "refus" in reason_l: return "Call - save the sale"
    return "Call customer" if valid else "No phone - check Shopify"


def whatsapp_message(name: str, reason: str, status: str) -> str:
    first = name.split()[0].title() if name.strip() else "there"
    reason_l, status_u = reason.casefold(), status.upper()
    close = "Please share the OTP with the delivery agent only after you have received the parcel. We are confident you will love our Mumchies products!"
    if "OUT FOR DELIVERY" in status_u:
        return f"Hi {first}, your Mumchies order is out for delivery today! Request you to please be available to receive it.\n\n{close}"
    if "wrong address" in reason_l or "address" in reason_l:
        return f"Hi {first}, our courier partner tried to deliver your Mumchies order but marked it undelivered. Your address is correct with us, so this may have been a missed attempt.\n\nRequest you to please accept the delivery when it is attempted next.\n\n{close}"
    if "future delivery" in reason_l or "asked" in reason_l:
        return f"Hi {first}, our courier partner tried to deliver your Mumchies order but it could not be completed.\n\nRequest you to please accept the delivery on the next attempt, which usually happens within a day.\n\n{close}"
    if any(term in reason_l for term in ("uncontactable", "not available", "not contactable")):
        return f"Hi {first}, our courier partner tried to reach you for delivering your Mumchies order but could not connect.\n\nRequest you to please keep your phone reachable and accept the delivery on the next attempt.\n\n{close}"
    return f"Hi {first}, our courier partner attempted delivery of your Mumchies order but was unsuccessful.\n\nRequest you to please accept the delivery when it is attempted next.\n\n{close}"


def whatsapp_url(phone: str, name: str, reason: str, status: str) -> str | None:
    cleaned = clean_phone(phone)
    return f"https://wa.me/{cleaned}?text={quote(whatsapp_message(name, reason, status))}" if cleaned else None


def _extract_sr(payload: Any) -> tuple[list[dict[str, Any]], int]:
    if isinstance(payload, list): return [x for x in payload if isinstance(x, dict)], 1
    if not isinstance(payload, dict): return [], 1
    data = payload.get("data")
    if isinstance(data, list):
        pagination = (payload.get("meta") or {}).get("pagination") or {}
        return data, int(pagination.get("total_pages") or pagination.get("last_page") or payload.get("last_page") or payload.get("total_pages") or 1)
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        pagination = (data.get("meta") or {}).get("pagination") or {}
        return data["data"], int(pagination.get("total_pages") or pagination.get("last_page") or data.get("last_page") or data.get("total_pages") or 1)
    return [], 1


def _sr_row(item: dict[str, Any]) -> CourierRow:
    return CourierRow(source="shiprocket", order_id=str(item.get("channel_order_id") or item.get("order_id") or item.get("id") or item.get("crm_order_id") or ""),
        awb=str(item.get("awb") or item.get("awb_code") or ""), customer_name=str(item.get("customer_name") or item.get("consignee") or item.get("buyer_name") or ""),
        phone=str(item.get("customer_phone") or item.get("phone") or item.get("customer_mobile") or ""), city=str(item.get("customer_city") or item.get("city") or ""),
        status=str(item.get("status") or item.get("current_status") or "UNDELIVERED"), failure_reason=str(item.get("latest_ndr_reason") or item.get("ndr_reason") or item.get("reason") or item.get("Latest NDR Reason") or "").strip(),
        attempts=_int(item.get("attempt_count") or item.get("attempts") or item.get("ndr_count") or item.get("total_attempts") or item.get("Attempt Count")),
        updated_at=parse_datetime(item.get("latest_ndr_date") or item.get("ndr_raised_at") or item.get("updated_at") or item.get("created_at") or item.get("event_date")), raw=item)


def _int(value: Any) -> int:
    try: return int(value or 0)
    except (ValueError, TypeError): return 0


async def fetch_shiprocket() -> SourceResult:
    started = time.monotonic(); endpoint = "/v1/external/ndr/all + /v1/external/shipments"
    if not settings.shiprocket_email or not settings.shiprocket_password:
        return SourceResult("shiprocket", endpoint, [], "failed", error="SHIPROCKET_EMAIL or SHIPROCKET_PASSWORD is missing.")
    result = SourceResult("shiprocket", endpoint, [])
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            auth = await client.post("https://apiv2.shiprocket.in/v1/external/auth/login", json={"email": settings.shiprocket_email, "password": settings.shiprocket_password})
            auth.raise_for_status(); token = auth.json().get("token")
            if not token: raise RuntimeError("Shiprocket authentication response did not contain a token.")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            seen_ids: set[str] = set(); seen_awbs: set[str] = set(); ndr_fetched = supplementary = duplicates = 0
            for page in range(1, 51):
                response = await client.get("https://apiv2.shiprocket.in/v1/external/ndr/all", headers=headers, params={"page": page, "per_page": 100})
                response.raise_for_status(); records, last_page = _extract_sr(response.json()); ndr_fetched += len(records)
                if not records: break
                for item in records:
                    row = _sr_row(item); oid = row.order_id; awb = row.awb
                    if (oid and oid in seen_ids) or (awb and awb in seen_awbs): duplicates += 1; continue
                    if oid: seen_ids.add(oid)
                    if awb: seen_awbs.add(awb)
                    result.rows.append(row)
                if page >= last_page: break
            today = datetime.now(); params_base = {"per_page": 100, "from": (today-timedelta(days=30)).strftime("%Y-%m-%d"), "to": today.strftime("%Y-%m-%d")}
            for page in range(1, 51):
                response = await client.get("https://apiv2.shiprocket.in/v1/external/shipments", headers=headers, params={"page": page, **params_base})
                response.raise_for_status(); records, last_page = _extract_sr(response.json())
                if not records: break
                for item in records:
                    status = str(item.get("status") or "").upper()
                    if not any(marker in status for marker in ("UNDELIVERED", "NDR", "OUT FOR DELIVERY")): continue
                    row = _sr_row(item)
                    if (row.order_id and row.order_id in seen_ids) or (row.awb and row.awb in seen_awbs): duplicates += 1; continue
                    if row.order_id: seen_ids.add(row.order_id)
                    if row.awb: seen_awbs.add(row.awb)
                    result.rows.append(row); supplementary += 1
                if page >= last_page: break
            result.fetched = ndr_fetched + supplementary; result.accepted = len(result.rows); result.skipped = duplicates
            result.details = {"ndr_all_fetched_count": ndr_fetched, "shipments_supplementary_count": supplementary, "duplicate_count": duplicates}
    except Exception as error:
        result.status = "failed"; result.error = _safe_http_error("Shiprocket", error)
    result.duration_ms = int((time.monotonic()-started)*1000); return result


def _safe_http_error(source: str, error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError): return f"{source} API returned HTTP {error.response.status_code}."
    return str(error)[:1000]


async def fetch_shadowfax() -> SourceResult:
    started=time.monotonic(); endpoint="POST shadowfax360 login; POST saruman dashboard/v2"; result=SourceResult("shadowfax", endpoint, [])
    token = None; login_error = None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if settings.shadowfax_email and settings.shadowfax_password_secret:
                try:
                    login=await client.post("https://shadowfax360.in/api/v1/login/", json={"email":settings.shadowfax_email,"password":settings.shadowfax_password_secret})
                    if login.status_code == 200:
                        body=login.json(); nested=body.get("data") if isinstance(body.get("data"),dict) else {}
                        token=body.get("token") or body.get("auth_token") or body.get("key") or nested.get("token") or nested.get("auth_token") or nested.get("key")
                    else: login_error=f"Shadowfax auto-login HTTP {login.status_code}."
                except Exception as error: login_error=_safe_http_error("Shadowfax auto-login",error)
            token = token or settings.shadowfax_effective_token
            if not token: raise RuntimeError(login_error or "No Shadowfax login credentials or token are configured.")
            headers={"Authorization":f"Token {token}","Content-Type":"application/json"}; today=datetime.now(); page=1
            while True:
                payload={"category":"customer_delivery","subcategory":"all_orders","page":page,"limit":100,"count":100,"awb_numbers":[],"order_start_date":(today-timedelta(days=30)).strftime("%Y-%m-%d"),"order_end_date":today.strftime("%Y-%m-%d"),"payment_mode":None}
                response=await client.post("https://saruman.shadowfax.in/ecommerce/client/4500/dashboard/v2/",headers=headers,json=payload)
                if response.status_code in (401,403): raise RuntimeError(f"Shadowfax credential failure: HTTP {response.status_code}.")
                response.raise_for_status(); body=response.json(); orders=body.get("data") if isinstance(body,dict) else []
                if not isinstance(orders,list): raise RuntimeError("Shadowfax returned an invalid dashboard response.")
                result.fetched += len(orders)
                for item in orders:
                    info=item.get("status_info") if isinstance(item.get("status_info"),dict) else {}; code=str(info.get("status_code") or "").casefold(); sub=str(info.get("subcategory_code") or "").casefold()
                    labels=(info.get("status_label"),info.get("subcategory_label"),item.get("status"))
                    is_ndr=not is_pre_pickup_state(code,sub,*labels) and is_ndr_eligible(code,sub,*labels)
                    if not is_ndr: result.skipped += 1; continue
                    result.rows.append(CourierRow("shadowfax",str(item.get("client_order_id") or ""),str(item.get("awb_number") or ""),str(item.get("consignee_name") or item.get("customer_name") or ""),str(item.get("consignee_phone") or item.get("consignee_contact") or item.get("customer_phone") or item.get("contact_number") or item.get("consignee_mobile") or ""),str(item.get("delivery_city") or ""),str(info.get("status_label") or item.get("status") or ""),str(info.get("subcategory_label") or ""),_int(item.get("attempt_number")),parse_datetime(info.get("last_updated")),item))
                total=_int(body.get("total_orders")); result.accepted=len(result.rows)
                if not orders or page*100>=total: break
                page += 1
            if login_error: result.details["login_fallback_warning"] = login_error
    except Exception as error: result.status="failed"; result.error=_safe_http_error("Shadowfax",error)
    result.duration_ms=int((time.monotonic()-started)*1000); return result


async def fetch_shopify() -> tuple[dict[str, ShopifyRecord], SourceResult]:
    started=time.monotonic(); result=SourceResult("shopify","GET Admin API 45-day orders",[]); records:dict[str,ShopifyRecord]={}
    try:
        if settings.shopify_store_url and settings.shopify_token:
            store=settings.shopify_store_url.replace("https://","").replace("http://","").strip("/"); url=f"https://{store}/admin/api/2024-01/orders.json"; params={"status":"any","created_at_min":(datetime.now(timezone.utc)-timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),"limit":250,"fields":"name,order_number,phone,customer,shipping_address,billing_address,created_at"}
            async with httpx.AsyncClient(timeout=30) as client:
                for _ in range(20):
                    response=await client.get(url,headers={"X-Shopify-Access-Token":settings.shopify_token},params=params); response.raise_for_status(); params=None
                    orders=response.json().get("orders",[]); result.fetched += len(orders)
                    for item in orders:
                        oid=str(item.get("name") or item.get("order_number") or "").strip().lstrip("#"); ship=item.get("shipping_address") or {}; bill=item.get("billing_address") or {}; customer=item.get("customer") or {}; default=customer.get("default_address") or {}
                        if oid: records[oid]=ShopifyRecord(str(item.get("phone") or ship.get("phone") or bill.get("phone") or customer.get("phone") or default.get("phone") or ""),str(ship.get("name") or " ".join(filter(None,[customer.get("first_name"),customer.get("last_name")])) or bill.get("name") or ""),parse_datetime(item.get("created_at")))
                    url=_next_link(response.headers.get("link"));
                    if not url: break
            result.details["enrichment_source"]="api_static_token"
        else:
            orders=await ShopifyService().get_orders_for_ndr_enrichment(); result.fetched=len(orders)
            for item in orders: records[str(item.order_number).lstrip("#")]=ShopifyRecord(str(item.phone or ""),str(item.customer_name or ""),parse_datetime(item.created_date))
            result.details["enrichment_source"]="api_oauth_alternate"
        if not records: raise RuntimeError("Shopify Admin API returned no orders.")
        result.accepted=len(records)
    except Exception as error:
        api_error=_safe_http_error("Shopify",error); records, warning = await _drive_fallback()
        if records: result.status="success"; result.accepted=len(records); result.details={"enrichment_source":"gdrive_csv","api_warning":api_error,**warning}
        else: result.status="failed"; result.error=api_error + (f" Drive fallback: {warning.get('error')}" if warning.get("error") else "")
    result.rows=list(records.values()); result.duration_ms=int((time.monotonic()-started)*1000); return records,result


def _next_link(header: str | None) -> str | None:
    for part in (header or "").split(","):
        if 'rel="next"' in part: return part.split(";")[0].strip().strip("<>")
    return None


async def _drive_fallback() -> tuple[dict[str,ShopifyRecord],dict[str,Any]]:
    if not settings.gdrive_folder_id or not settings.gdrive_service_account_json: return {},{"error":"Google Drive fallback is not configured."}
    def load():
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        credentials=service_account.Credentials.from_service_account_info(json.loads(settings.gdrive_service_account_json),scopes=["https://www.googleapis.com/auth/drive.readonly"]); service=build("drive","v3",credentials=credentials,cache_discovery=False)
        files=service.files().list(q=f"'{settings.gdrive_folder_id}' in parents and mimeType='text/csv' and trashed=false",orderBy="modifiedTime desc",pageSize=1,fields="files(id,name,modifiedTime)").execute().get("files",[])
        if not files: return {},{"error":"No Shopify CSV was found in Google Drive."}
        file=files[0]; buffer=io.BytesIO(); downloader=MediaIoBaseDownload(buffer,service.files().get_media(fileId=file["id"])); done=False
        while not done: _,done=downloader.next_chunk()
        buffer.seek(0); reader=csv.DictReader(io.TextIOWrapper(buffer,encoding="utf-8-sig")); columns=reader.fieldnames or []
        order_col=next((c for c in columns if "order" in c.casefold() and "name" in c.casefold()),None) or next((c for c in columns if c.casefold() in {"name","order id","order_id"}),None); phone_col=next((c for c in columns if "phone" in c.casefold()),None); created_col=next((c for c in columns if "created" in c.casefold()),None); name_col=next((c for c in columns if "billing" in c.casefold() and "name" in c.casefold() and "last" not in c.casefold()),None)
        output={}
        if order_col and phone_col:
            for row in reader:
                oid=str(row.get(order_col) or "").strip().lstrip("#"); phone=str(row.get(phone_col) or "").strip(); name=str(row.get(name_col) or "").strip() if name_col else ""
                if oid and phone.casefold()!="nan": output[oid]=ShopifyRecord(phone,"" if name.casefold()=="nan" else name,parse_datetime(row.get(created_col)) if created_col else None)
        modified=parse_datetime(file.get("modifiedTime")); age=(datetime.now(timezone.utc)-modified).days if modified else None
        return output,{"csv_name":file.get("name"),"stale_warning":f"Google Drive Shopify CSV is {age} days old." if age is not None and age>7 else None}
    try: return await asyncio.to_thread(load)
    except Exception as error: return {},{"error":str(error)[:1000]}


async def fetch_delhivery(shopify: dict[str,ShopifyRecord]) -> SourceResult:
    started=time.monotonic(); result=SourceResult("delhivery","GET /api/v1/packages/json by ref_ids",[])
    if not settings.delhivery_token: result.status="failed"; result.error="DELHIVERY_TOKEN is missing."; return result
    cutoff=datetime.now(timezone.utc)-timedelta(days=15); candidates=[oid for oid,rec in shopify.items() if rec.created is None or rec.created>=cutoff]
    ndr_reasons=("consignee unavailable","consignee not available","maximum attempts reached","office/institute closed","office closed","residence closed","consignee refused","refused to accept","address incomplete","address incorrect","wrong address","consignee unreachable","no response","not attempted","cash not ready","amount not ready","cod not ready","delivery rescheduled","future delivery","consignee shifted","premises closed"); ignore=("received at facility","in transit","shipment picked","added to bag","bag received","departed","arrived","shipment created","manifested","connected")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for start in range(0,len(candidates),25):
                response=await client.get("https://track.delhivery.com/api/v1/packages/json/",params={"ref_ids":",".join(candidates[start:start+25])},headers={"Authorization":f"Token {settings.delhivery_token}","Content-Type":"application/json"})
                if response.status_code in (401,403): raise RuntimeError(f"Delhivery credential failure: HTTP {response.status_code}.")
                response.raise_for_status(); shipments=response.json().get("ShipmentData",[]); result.fetched += len(shipments)
                for wrapper in shipments:
                    item=wrapper.get("Shipment",{}) if isinstance(wrapper,dict) else {}; status_obj=item.get("Status") or {}; status=str(status_obj.get("Status") or ""); status_type=str(status_obj.get("StatusType") or "").upper(); instructions=str(status_obj.get("Instructions") or ""); reason_l=instructions.casefold(); status_l=status.casefold(); real=any(x in reason_l for x in ndr_reasons); ofd=("out for delivery" in reason_l or "dispatched" in status_l) and not real
                    if status_type in {"DL","RT"} or (any(x in reason_l for x in ignore) and not real) or not(real or ofd): result.skipped += 1; continue
                    attempts=0; latest=""
                    for scan in item.get("Scans") or []:
                        detail=scan.get("ScanDetail",{}) if isinstance(scan,dict) else {}; attempts += int("pending" in str(detail.get("Scan") or "").casefold()); latest=detail.get("ScanDateTime") or latest
                    consignee=item.get("Consignee") or {}; result.rows.append(CourierRow("delhivery",str(item.get("ReferenceNo") or "").lstrip("#"),str(item.get("AWB") or ""),str(consignee.get("Name") or ""),"",str(consignee.get("City") or ""),"OUT FOR DELIVERY" if ofd else "UNDELIVERED",instructions,attempts,parse_datetime(status_obj.get("StatusDateTime") or latest),item))
                await asyncio.sleep(.4)
        result.accepted=len(result.rows)
    except Exception as error: result.status="failed"; result.error=_safe_http_error("Delhivery",error)
    result.duration_ms=int((time.monotonic()-started)*1000); return result
