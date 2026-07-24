import secrets

import pytest
from fastapi.testclient import TestClient

from app.core.auth import hash_password
from app.core.config import settings
from app.main import app


@pytest.fixture()
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_admin_username", "test-admin")
    monkeypatch.setattr(settings, "auth_admin_password_hash", hash_password("correct-test-password"))
    monkeypatch.setattr(settings, "auth_session_secret", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "auth_session_minutes", 5)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    with TestClient(app) as client:
        yield client


def test_valid_login(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "test-admin", "password": "correct-test-password"},
    )
    assert response.status_code == 200
    assert response.json()["username"] == "test-admin"
    assert response.json()["csrf_token"]
    assert settings.auth_cookie_name in response.cookies
    assert auth_client.get("/api/v1/auth/session").status_code == 200


def test_invalid_login(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"username": "test-admin", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert settings.auth_cookie_name not in response.cookies


def test_protected_endpoint_without_login(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/orders")
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}


def test_logout_invalidates_browser_session(auth_client: TestClient) -> None:
    auth_client.post(
        "/api/v1/auth/login",
        json={"username": "test-admin", "password": "correct-test-password"},
    )
    response = auth_client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "logged_out"}
    assert auth_client.get("/api/v1/auth/session").status_code == 401
