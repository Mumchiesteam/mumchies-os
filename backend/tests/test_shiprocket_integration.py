from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.orders import router as orders_router
from app.db.session import get_db
from app.db.base import Base
from app.models.shiprocket import ShiprocketShipment
from app.repositories.shiprocket import get_shipment
from app.services import shiprocket as shiprocket_module
from app.services.shiprocket import ShiprocketAPIError, ShiprocketService


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: object | None = None, content: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.content = content
        self.headers = headers or {}
        self.text = content.decode("utf-8", errors="ignore") if content else ""

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, object | None, object | None]] = []

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    async def get(self, url: str, params=None, headers=None):
        self.calls.append(("GET", url, params, headers))
        return self.responses.pop(0)

    async def post(self, url: str, json=None, data=None, headers=None):  # noqa: A002
        self.calls.append(("POST", url, json or data, headers))
        return self.responses.pop(0)

    async def put(self, url: str, json=None, headers=None):  # noqa: A002
        self.calls.append(("PUT", url, json, headers))
        return self.responses.pop(0)


@pytest.fixture()
def sqlite_session(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'shiprocket.db'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def install_fake_client(monkeypatch: pytest.MonkeyPatch, responses: list[FakeResponse]) -> FakeClient:
    fake_client = FakeClient(responses)
    monkeypatch.setattr(shiprocket_module.httpx, "AsyncClient", lambda timeout=30.0: fake_client)
    shiprocket_module.ShiprocketService._token_cache = None
    return fake_client


@pytest.mark.anyio
async def test_authentication_and_token_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = install_fake_client(
        monkeypatch,
        [
            FakeResponse(json_data={"token": "jwt-1", "expires_in": 3600}),
        ],
    )
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_email", "a@b.com")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_password", "secret")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_pickup", "Mumchies Factory")

    service = ShiprocketService()
    token = await service.get_token()
    token2 = await service.get_token()

    assert token == "jwt-1"
    assert token2 == "jwt-1"
    assert len(fake_client.calls) == 1


@pytest.mark.anyio
async def test_invalid_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(monkeypatch, [FakeResponse(status_code=401, json_data={"message": "Invalid credentials"})])
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_email", "a@b.com")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_password", "wrong")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_pickup", "Mumchies Factory")

    with pytest.raises(ShiprocketAPIError, match="Invalid credentials"):
        await ShiprocketService().get_token()


@pytest.mark.anyio
async def test_token_expiry_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = install_fake_client(
        monkeypatch,
        [
            FakeResponse(json_data={"token": "jwt-1", "expires_in": 1}),
            FakeResponse(json_data={"token": "jwt-2", "expires_in": 3600}),
        ],
    )
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_email", "a@b.com")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_password", "secret")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_pickup", "Mumchies Factory")

    service = ShiprocketService()
    assert await service.get_token() == "jwt-1"
    service._token_cache = {"token": "jwt-1", "expires_at": time.time() - 1}
    assert await service.get_token() == "jwt-2"
    assert len(fake_client.calls) == 2


@pytest.mark.anyio
async def test_pickup_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(
        monkeypatch,
        [
            FakeResponse(json_data={"token": "jwt-1", "expires_in": 3600}),
            FakeResponse(json_data={"data": {"shipping_address": [{"pickup_location": "Mumchies Factory"}]}}),
        ],
    )
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_email", "a@b.com")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_password", "secret")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_pickup", "Mumchies Factory")

    result = await ShiprocketService().health()
    assert result.authenticated is True
    assert result.pickup_exists is True
    assert result.pickup_location == "Mumchies Factory"
    assert result.message == "Connected"


@pytest.mark.anyio
async def test_serviceability_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(
        monkeypatch,
        [
            FakeResponse(json_data={"token": "jwt-1", "expires_in": 3600}),
            FakeResponse(
                json_data={
                    "data": {
                        "available_courier_companies": [
                            {"courier_company_id": 11, "courier_name": "Shiprocket X", "freight_charge": 85, "etd": "3 Days", "cod": True},
                        ]
                    }
                }
            ),
        ],
    )
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_email", "a@b.com")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_password", "secret")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_pickup", "Mumchies Factory")

    quotes = await ShiprocketService().serviceability("400001", "410401", 1.2, True)
    assert quotes[0].courier_id == "11"
    assert quotes[0].courier_name == "Shiprocket X"
    assert quotes[0].rate == 85.0
    assert quotes[0].cod_supported is True
    assert quotes[0].prepaid_supported is True


@pytest.mark.anyio
async def test_shipment_booking_and_persistence(monkeypatch: pytest.MonkeyPatch, sqlite_session) -> None:
    install_fake_client(
        monkeypatch,
        [
            FakeResponse(json_data={"token": "jwt-1", "expires_in": 3600}),
            FakeResponse(json_data={"order_id": "9001", "shipment_id": "7001", "awb_code": "AWB123", "courier_company_id": 88, "courier_name": "Shiprocket X"}),
            FakeResponse(json_data={"awb_code": "AWB123", "courier_name": "Shiprocket X"}),
        ],
    )
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_email", "a@b.com")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_password", "secret")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_pickup", "Mumchies Factory")

    payload = {"order_id": "1", "shipment_order_id": "1", "courier_id": "88"}
    result = await ShiprocketService().create_shipment(sqlite_session, "1", payload, "88")
    shipment = get_shipment(sqlite_session, "1")

    assert result["shipment"]["awb"] == "AWB123"
    assert shipment is not None
    assert shipment.shiprocket_order_id == "9001"
    assert shipment.shipment_id == "7001"
    assert shipment.awb == "AWB123"
    assert shipment.courier_id == "88"
    assert shipment.courier_name == "Shiprocket X"
    assert shipment.booking_status == "booked"


@pytest.mark.anyio
async def test_label_retrieval(monkeypatch: pytest.MonkeyPatch, sqlite_session) -> None:
    sqlite_session.add(ShiprocketShipment(order_id="1", awb="AWB123"))
    sqlite_session.commit()
    install_fake_client(
        monkeypatch,
        [
            FakeResponse(json_data={"token": "jwt-1", "expires_in": 3600}),
            FakeResponse(content=b"%PDF-1.4", headers={"content-type": "application/pdf"}),
        ],
    )
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_email", "a@b.com")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_password", "secret")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_pickup", "Mumchies Factory")

    app = FastAPI()
    app.include_router(orders_router, prefix="/api/v1")
    def override_db():
        yield sqlite_session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    response = client.get("/api/v1/orders/1/shipping-label")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content == b"%PDF-1.4"


@pytest.mark.anyio
async def test_tracking_and_address_update(monkeypatch: pytest.MonkeyPatch, sqlite_session) -> None:
    sqlite_session.add(ShiprocketShipment(order_id="1", awb="AWB123"))
    sqlite_session.commit()
    install_fake_client(
        monkeypatch,
        [
            FakeResponse(json_data={"token": "jwt-1", "expires_in": 3600}),
            FakeResponse(json_data={"tracking_data": {"shipment_track": [{"current_status": "In Transit"}], "track_url": "https://example.com/track"}}),
            FakeResponse(json_data={"status": "success"}),
        ],
    )
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_email", "a@b.com")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_password", "secret")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_pickup", "Mumchies Factory")

    tracking_snapshot = await ShiprocketService().sync_tracking(sqlite_session, "1", "AWB123")
    assert tracking_snapshot["latest_status"] == "In Transit"
    assert tracking_snapshot["tracking_url"] == "https://example.com/track"

    ShiprocketService._token_cache = {"token": "jwt-1", "expires_at": time.time() + 3600}
    update_response = await ShiprocketService().update_address("AWB123", {"address": "new"})
    assert update_response["status"] == "success"


@pytest.mark.anyio
async def test_address_update_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_client(
        monkeypatch,
        [
            FakeResponse(json_data={"token": "jwt-1", "expires_in": 3600}),
            FakeResponse(status_code=400, json_data={"message": "Shipment cannot be updated"}),
        ],
    )
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_email", "a@b.com")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_password", "secret")
    monkeypatch.setattr(shiprocket_module.settings, "shiprocket_pickup", "Mumchies Factory")

    with pytest.raises(ShiprocketAPIError, match="Shipment cannot be updated"):
        await ShiprocketService().update_address("AWB123", {"address": "new"})
