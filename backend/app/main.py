from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import hmac
import logging

from app.api.router import api_router
from app.core.auth import read_session
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.models.ndr import NDRCase, NDRSyncRun
from sqlalchemy import func, select

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.state.session_factory = SessionLocal
logging.getLogger(__name__).info("NDR source configuration: %s", settings.ndr_configuration())


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    public_paths = {"/health", f"{settings.api_v1_prefix}/auth/login", f"{settings.api_v1_prefix}/auth/logout"}
    signed_provider_webhook = request.method == "POST" and request.url.path.startswith(f"{settings.api_v1_prefix}/couriers/webhooks/")
    if not settings.auth_enabled or request.method == "OPTIONS" or request.url.path in public_paths or signed_provider_webhook:
        return await call_next(request)
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
    with request.app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.username == session.username))
        if user is None or not user.is_active:
            response = JSONResponse(status_code=401, content={"detail": "Authentication required."})
            response.delete_cookie(settings.auth_cookie_name, path="/")
            return response
        db.expunge(user)
    if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(
        request.headers.get("X-CSRF-Token", ""),
        session.csrf_token,
    ):
        return JSONResponse(status_code=403, content={"detail": "Invalid CSRF token."})
    request.state.auth_username = session.username
    request.state.auth_user = user
    request.state.csrf_token = session.csrf_token
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
def health_check() -> dict:
    """Return service and privacy-safe NDR pipeline health without customer data."""
    result: dict = {"status": "ok"}
    try:
        with SessionLocal() as db:
            run = db.scalar(select(NDRSyncRun).order_by(NDRSyncRun.started_at.desc()).limit(1))
            health = run.source_health or {} if run else {}
            result["ndr"] = {
                "last_sync_status": run.status if run else None,
                "case_count": db.scalar(select(func.count()).select_from(NDRCase)) or 0,
                "source_counts": {name: value.get("accepted_count", 0) for name, value in health.items() if name in {"shiprocket", "shadowfax", "delhivery"}},
                "phone_match_percentage": (health.get("shopify") or {}).get("match_percentage"),
            }
    except Exception:
        result["ndr"] = {"last_sync_status": "unavailable"}
    return result
