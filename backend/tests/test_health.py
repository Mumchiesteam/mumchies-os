from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_operational_write_cors_preflight() -> None:
    response = client.options(
        "/api/v1/orders/example/call-logs",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    allowed_methods = response.headers["access-control-allow-methods"]
    assert "POST" in allowed_methods
    assert "PUT" in allowed_methods
