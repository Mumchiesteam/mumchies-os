import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import create_session, verify_password
from app.core.config import settings
from app.core.identity import current_user
from app.core.users import normalize_username
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginPayload(BaseModel):
    username: str
    password: str


def _require_session_secret() -> str:
    if not settings.auth_session_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    return settings.auth_session_secret


@router.post("/login")
def login(payload: LoginPayload, response: Response, db: Session = Depends(get_db)) -> dict[str, object]:
    session_secret = _require_session_secret()
    try:
        username = normalize_username(payload.username)
    except ValueError:
        username = ""
    user = db.scalar(select(User).where(User.username == username)) if username else None
    if user is None and settings.auth_admin_username and settings.auth_admin_password_hash:
        legacy_username = normalize_username(settings.auth_admin_username)
        if secrets_compare(username, legacy_username) and verify_password(payload.password, settings.auth_admin_password_hash):
            user = User(username=legacy_username, display_name=settings.auth_admin_username.strip(), password_hash=settings.auth_admin_password_hash, role="owner", is_active=True)
            db.add(user)
            db.flush()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    max_age = settings.auth_session_minutes * 60
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=create_session(user.username, csrf_token, session_secret, max_age),
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )
    return {"username": user.username, "display_name": user.display_name, "role": user.role, "csrf_token": csrf_token}


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )
    return {"status": "logged_out"}


@router.get("/session")
def session(request: Request) -> dict[str, object]:
    user = current_user(request)
    return {"username": user.username, "display_name": user.display_name, "role": user.role, "csrf_token": request.state.csrf_token}


def secrets_compare(candidate: str, expected: str) -> bool:
    import hmac

    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
