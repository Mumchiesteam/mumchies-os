import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import hmac
import logging
import os
import time

from app.api.router import api_router
from app.api.routes.dashboard import _dashboard_key, _dashboard_refresh_tasks, _period, _start_dashboard_refresh
from app.api.routes.analytics import _analytics_tasks, _key as _analytics_key, start_analytics_refresh
from app.api.routes.orders import _start_reconciliation_refresh
from app.core.auth import read_session
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.report_snapshots import ReportSnapshotStore
from app.services.order_read_models import cache_orders
from app.services.shopify import ShopifyService
from app.services.shipment_poller import poller_status, tracking_poller_loop
from sqlalchemy import select

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.state.session_factory = SessionLocal
logging.getLogger(__name__).info(
    "NDR mode: github_import (ingestion enabled: %s)",
    bool(settings.ndr_ingest_token),
)


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    request_started = time.perf_counter()
    auth_started = time.perf_counter()
    public_paths = {"/health", f"{settings.api_v1_prefix}/auth/login", f"{settings.api_v1_prefix}/auth/logout"}
    signed_provider_webhook = request.method == "POST" and request.url.path.startswith(f"{settings.api_v1_prefix}/couriers/webhooks/")
    signed_ndr_import = request.method == "POST" and request.url.path == f"{settings.api_v1_prefix}/ndr/import"
    if not settings.auth_enabled or request.method == "OPTIONS" or request.url.path in public_paths or signed_provider_webhook or signed_ndr_import:
        response = await call_next(request)
        prior = response.headers.get("Server-Timing")
        total = f"request_total;dur={(time.perf_counter() - request_started) * 1000:.2f}"
        response.headers["Server-Timing"] = f"{prior}, {total}" if prior else total
        return response
    if not settings.auth_session_secret:
        return JSONResponse(status_code=503, content={"detail": "Authentication is not configured."})
    session = read_session(
        request.cookies.get(settings.auth_cookie_name, ""),
        settings.auth_session_secret,
    )
    if session is None:
        response = JSONResponse(status_code=401, content={"detail": "Authentication required."})
        response.delete_cookie(settings.auth_cookie_name, path="/")
        return response
    session_ms = (time.perf_counter() - auth_started) * 1000
    auth_db_started = time.perf_counter()
    with request.app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.username == session.username))
        if user is None or not user.is_active:
            response = JSONResponse(status_code=401, content={"detail": "Authentication required."})
            response.delete_cookie(settings.auth_cookie_name, path="/")
            return response
        db.expunge(user)
    auth_db_ms = (time.perf_counter() - auth_db_started) * 1000
    if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(
        request.headers.get("X-CSRF-Token", ""),
        session.csrf_token,
    ):
        return JSONResponse(status_code=403, content={"detail": "Invalid CSRF token."})
    request.state.auth_username = session.username
    request.state.auth_user = user
    request.state.csrf_token = session.csrf_token
    response = await call_next(request)
    prior = response.headers.get("Server-Timing")
    total_ms = (time.perf_counter() - request_started) * 1000
    timings = f"auth_session;dur={session_ms:.2f}, auth_db;dur={auth_db_ms:.2f}, request_total;dur={total_ms:.2f}"
    response.headers["Server-Timing"] = f"{prior}, {timings}" if prior else timings
    if request.url.path.endswith(("/address/save-verify", "/book")):
        logging.getLogger(__name__).info(
            "interactive_request path=%s auth_session_ms=%.2f auth_db_ms=%.2f total_ms=%.2f",
            request.url.path, session_ms, auth_db_ms, total_ms,
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.on_event("startup")
async def warm_management_report_snapshots() -> None:
    """Refresh persisted report snapshots without delaying service readiness."""
    async def warm_sequentially() -> None:
        # Give interactive traffic priority after a cold start. Heavy provider
        # reads are intentionally staggered rather than launched together.
        await asyncio.sleep(15)
        # Populate the local canonical read model once per deploy. Dispatch/NDR reads
        # never call Shopify themselves.
        try:
            recent = await ShopifyService().get_orders_created_between(
                datetime.now(timezone.utc) - timedelta(days=90), datetime.now(timezone.utc)
            )
            with SessionLocal() as db:
                cache_orders(db, recent)
        except Exception:
            logging.getLogger(__name__).exception("Canonical order read-model warmup failed.")
        start_at, end_at, label = _period("today", None, None)
        key = _dashboard_key("today", start_at, end_at)
        _start_dashboard_refresh(key, "today", start_at, end_at, label)
        task = _dashboard_refresh_tasks.get(key)
        if task:
            await task
        await asyncio.sleep(30)
        analytics_start, analytics_end, analytics_label = _period("last_30_days", None, None)
        analytics_key = _analytics_key("last_30_days", analytics_start, analytics_end, "all", "all")
        start_analytics_refresh(analytics_key, analytics_start, analytics_end, "last_30_days", analytics_label)
        analytics_task = _analytics_tasks.get(analytics_key)
        if analytics_task:
            await analytics_task
        await asyncio.sleep(30)
        _start_reconciliation_refresh()

    asyncio.create_task(warm_sequentially())


@app.on_event("startup")
async def start_shipment_tracking_poller() -> None:
    """Start one conservative GET-only tracking loop per backend process."""
    if settings.shipment_tracking_poller_enabled:
        async def deferred_poller() -> None:
            await asyncio.sleep(60)
            await tracking_poller_loop(app.state.session_factory)
        app.state.shipment_tracking_poller_task = asyncio.create_task(deferred_poller())


@app.get("/health", tags=["health"])
def health_check() -> dict:
    """Return deployment identity and the configured NDR ingestion mode."""
    start_at, end_at, _ = _period("today", None, None)
    dashboard_snapshot = ReportSnapshotStore.get(_dashboard_key("today", start_at, end_at))
    reconciliation_snapshot = ReportSnapshotStore.get("reconciliation")
    analytics_start, analytics_end, _ = _period("last_30_days", None, None)
    analytics_snapshot = ReportSnapshotStore.get(_analytics_key("last_30_days", analytics_start, analytics_end, "all", "all"))
    tracking_poller = poller_status()
    return {
        "status": "ok",
        "git_sha": os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "unknown",
        "ndr_mode": "github_import",
        "ndr_import_enabled": bool(settings.ndr_ingest_token),
        "shipment_tracking_poller": {
            "enabled": tracking_poller.get("enabled"),
            "last_poll_started": tracking_poller.get("last_poll_started"),
            "last_poll_completed": tracking_poller.get("last_poll_completed"),
            "state": tracking_poller.get("state"),
            "shipments_attempted": tracking_poller.get("shipments_attempted", 0),
            "shipments_failed": tracking_poller.get("shipments_failed", 0),
            "new_events_persisted": tracking_poller.get("new_events_persisted", 0),
            "shadowfax_enabled": tracking_poller.get("providers", {}).get("shadowfax", False),
        },
        "report_snapshots": {
            "dashboard_ready": bool(dashboard_snapshot and dashboard_snapshot.get("data")),
            "dashboard_refreshed_at": (dashboard_snapshot or {}).get("last_refreshed_at"),
            "dashboard_refresh_error": (dashboard_snapshot or {}).get("refresh_error"),
            "reconciliation_ready": bool(reconciliation_snapshot and reconciliation_snapshot.get("data")),
            "reconciliation_refreshed_at": (reconciliation_snapshot or {}).get("last_refreshed_at"),
            "reconciliation_refresh_error": (reconciliation_snapshot or {}).get("refresh_error"),
            "analytics_ready": bool(analytics_snapshot and analytics_snapshot.get("data")),
            "analytics_refreshed_at": (analytics_snapshot or {}).get("last_refreshed_at"),
        },
    }
