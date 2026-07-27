from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import hmac
import logging
import os

from app.api.router import api_router
from app.core.auth import read_session
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from sqlalchemy import select

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.state.session_factory = SessionLocal
logging.getLogger(__name__).info(
    "NDR mode: github_import (ingestion enabled: %s)",
    bool(settings.ndr_ingest_token),
)


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    public_paths = {"/health", f"{settings.api_v1_prefix}/auth/login", f"{settings.api_v1_prefix}/auth/logout"}
    signed_provider_webhook = request.method == "POST" and request.url.path.startswith(f"{settings.api_v1_prefix}/couriers/webhooks/")
    signed_ndr_import = request.method == "POST" and request.url.path == f"{settings.api_v1_prefix}/ndr/import"
    if not settings.auth_enabled or request.method == "OPTIONS" or request.url.path in public_paths or signed_provider_webhook or signed_ndr_import:
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
    """Return deployment identity and the configured NDR ingestion mode."""
    return {
        "status": "ok",
        "git_sha": os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "unknown",
        "ndr_mode": "github_import",
        "ndr_import_enabled": bool(settings.ndr_ingest_token),
    }
