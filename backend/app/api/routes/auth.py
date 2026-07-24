import secrets

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.core.auth import create_session, verify_password
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginPayload(BaseModel):
    username: str
    password: str


def _require_configuration() -> tuple[str, str, str]:
    if not (
        settings.auth_admin_username
        and settings.auth_admin_password_hash
        and settings.auth_session_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    return (
        settings.auth_admin_username,
        settings.auth_admin_password_hash,
        settings.auth_session_secret,
    )


@router.post("/login")
def login(payload: LoginPayload, response: Response) -> dict[str, str]:
    username, password_hash, session_secret = _require_configuration()
    valid_username = secrets_compare(payload.username, username)
    valid_password = verify_password(payload.password, password_hash)
    if not (valid_username and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    max_age = settings.auth_session_minutes * 60
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=create_session(username, csrf_token, session_secret, max_age),
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )
    return {"username": username, "csrf_token": csrf_token}


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
def session(request: Request) -> dict[str, str]:
    return {"username": request.state.auth_username, "csrf_token": request.state.csrf_token}


def secrets_compare(candidate: str, expected: str) -> bool:
    import hmac

    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
