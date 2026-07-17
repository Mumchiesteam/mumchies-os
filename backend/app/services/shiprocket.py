"""Shiprocket integration for Mumchies OS."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.shiprocket import get_shipment, snapshot, upsert_shipment


class ShiprocketConfigurationError(RuntimeError):
    """Raised when Shiprocket credentials have not been configured."""


class ShiprocketAPIError(RuntimeError):
    """Raised when Shiprocket rejects a request or returns malformed data."""


@dataclass(slots=True)
class ShiprocketHealthResult:
    configured: bool
    authenticated: bool
    pickup_exists: bool
    pickup_location: str | None
    message: str


@dataclass(slots=True)
class CourierQuote:
    courier_id: str | None
    courier_name: str
    rate: float
    estimated_delivery_days: int | None
    cod_supported: bool
    prepaid_supported: bool


class ShiprocketService:
    """Reusable wrapper around the Shiprocket API."""

    _token_cache: dict[str, Any] | None = None
    _token_lock = asyncio.Lock()

    def __init__(self, email: str | None = None, password: str | None = None, pickup_location: str | None = None) -> None:
        self.email = email or settings.shiprocket_email
        self.password = password or settings.shiprocket_password
        self.pickup_location = pickup_location or settings.shiprocket_pickup

    def _validate_configuration(self) -> None:
        if not all((self.email, self.password, self.pickup_location)):
            raise ShiprocketConfigurationError("SHIPROCKET_EMAIL, SHIPROCKET_PASSWORD, and SHIPROCKET_PICKUP must be configured.")

    @staticmethod
    def _safe_message(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:
            return "Shiprocket request failed."
        if isinstance(data, dict):
            message = data.get("message") or data.get("error") or data.get("status")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return "Shiprocket request failed."

    async def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self.get_token()}"}

    async def get_token(self) -> str:
        self._validate_configuration()
        cached = self._token_cache
        now = time.time()
        if cached and cached["expires_at"] > now:
            return cached["token"]

        async with self._token_lock:
            cached = self._token_cache
            now = time.time()
            if cached and cached["expires_at"] > now:
                return cached["token"]

            url = "https://apiv2.shiprocket.in/v1/external/auth/login"
            payload = {"email": self.email, "password": self.password}
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
            if response.status_code >= 400:
                raise ShiprocketAPIError(self._safe_message(response))

            data = response.json()
            token = data.get("token")
            if not token:
                raise ShiprocketAPIError("Shiprocket did not return an auth token.")

            expires_in = int(data.get("expires_in") or 12 * 60 * 60)
            self._token_cache = {
                "token": token,
                "expires_at": time.time() + max(expires_in - 120, 60),
            }
            return token

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.get(url, params=params, headers=await self._auth_headers())

    async def _post(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(url, json=payload, headers=await self._auth_headers())

    async def _put(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.put(url, json=payload, headers=await self._auth_headers())

    async def _pickup_locations(self) -> list[dict[str, Any]]:
        response = await self._get("https://apiv2.shiprocket.in/v1/external/settings/company/pickup")
        if response.status_code >= 400:
            raise ShiprocketAPIError(self._safe_message(response))
        data = response.json().get("data", {})
        return data.get("shipping_address", []) or []

    async def health(self) -> ShiprocketHealthResult:
        self._validate_configuration()
        token = await self.get_token()
        pickup_locations = await self._pickup_locations()
        pickup_exists = any(
            str(location.get("pickup_location", "")).strip().lower() == str(self.pickup_location).strip().lower()
            for location in pickup_locations
        )
        message = "Connected" if pickup_exists else f'Pickup location "{self.pickup_location}" was not found in Shiprocket.'
        return ShiprocketHealthResult(
            configured=True,
            authenticated=bool(token),
            pickup_exists=pickup_exists,
            pickup_location=self.pickup_location,
            message=message,
        )

    async def serviceability(self, pickup_postcode: str, delivery_postcode: str, weight: float, cod: bool) -> list[CourierQuote]:
        response = await self._get(
            "https://apiv2.shiprocket.in/v1/external/courier/serviceability/",
            params={
                "pickup_postcode": pickup_postcode,
                "delivery_postcode": delivery_postcode,
                "weight": weight,
                "cod": 1 if cod else 0,
            },
        )
        if response.status_code >= 400:
            raise ShiprocketAPIError(self._safe_message(response))
        payload = response.json().get("data", {})
        available = payload.get("available_courier_companies", []) or []
        quotes: list[CourierQuote] = []
        for courier in available:
            estimated = courier.get("etd")
            days = None
            if isinstance(estimated, str):
                digits = "".join(ch for ch in estimated if ch.isdigit())
                days = int(digits) if digits else None
            quotes.append(CourierQuote(
                courier_id=str(courier.get("courier_company_id")) if courier.get("courier_company_id") is not None else None,
                courier_name=str(courier.get("courier_name") or "Unknown courier"),
                rate=float(courier.get("freight_charge") or courier.get("rate") or 0),
                estimated_delivery_days=days,
                cod_supported=bool(courier.get("cod", False)),
                prepaid_supported=True,
            ))
        return quotes

    async def create_order(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._post("https://apiv2.shiprocket.in/v1/external/orders/create/adhoc", order_payload)
        if response.status_code >= 400:
            raise ShiprocketAPIError(self._safe_message(response))
        return response.json()

    async def assign_courier_and_generate_awb(self, shipment_id: str, courier_id: str) -> dict[str, Any]:
        response = await self._post(
            "https://apiv2.shiprocket.in/v1/external/courier/assign/awb",
            {"shipment_id": shipment_id, "courier_id": courier_id},
        )
        if response.status_code >= 400:
            raise ShiprocketAPIError(self._safe_message(response))
        return response.json()

    async def create_shipment(self, db: Session, order_id: str, order_payload: dict[str, Any], courier_id: str | None = None) -> dict[str, Any]:
        created_order = await self.create_order(order_payload)
        order_data = created_order.get("order_id") or created_order.get("data", {}).get("order_id")
        shipment_id = created_order.get("shipment_id") or created_order.get("data", {}).get("shipment_id")
        awb = created_order.get("awb_code") or created_order.get("data", {}).get("awb_code")
        selected_courier_id = courier_id or created_order.get("courier_company_id") or created_order.get("data", {}).get("courier_company_id")
        courier_name = created_order.get("courier_name") or created_order.get("data", {}).get("courier_name")
        assign_response = None
        if shipment_id and selected_courier_id:
            assign_response = await self.assign_courier_and_generate_awb(str(shipment_id), str(selected_courier_id))
            awb = awb or assign_response.get("awb_code") or assign_response.get("data", {}).get("awb_code")
            courier_name = courier_name or assign_response.get("courier_name") or assign_response.get("data", {}).get("courier_name")
        persisted = upsert_shipment(
            db,
            order_id,
            shiprocket_order_id=str(order_data) if order_data is not None else None,
            shipment_id=str(shipment_id) if shipment_id is not None else None,
            awb=str(awb) if awb is not None else None,
            courier_name=str(courier_name) if courier_name is not None else None,
            courier_id=str(selected_courier_id) if selected_courier_id is not None else None,
            booking_status="booked",
            booked_at=datetime.now(timezone.utc),
            latest_status="booked",
            last_synced_at=datetime.now(timezone.utc),
            tracking_url=created_order.get("tracking_url") or created_order.get("data", {}).get("tracking_url"),
            label_url=created_order.get("label_url") or created_order.get("data", {}).get("label_url"),
        )
        return {"shipment": snapshot(persisted), "shiprocket": created_order, "assignment": assign_response}

    async def tracking(self, awb: str) -> dict[str, Any]:
        response = await self._get(f"https://apiv2.shiprocket.in/v1/external/courier/track/awb/{awb}")
        if response.status_code >= 400:
            raise ShiprocketAPIError(self._safe_message(response))
        return response.json()

    async def fetch_label(self, awb: str) -> httpx.Response:
        response = await self._get(f"https://apiv2.shiprocket.in/v1/external/courier/generate/label/{awb}")
        if response.status_code >= 400:
            raise ShiprocketAPIError(self._safe_message(response))
        return response

    async def update_address(self, awb: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._put(f"https://apiv2.shiprocket.in/v1/external/courier/awb/update/{awb}", payload)
        if response.status_code >= 400:
            raise ShiprocketAPIError(self._safe_message(response))
        return response.json()

    async def sync_tracking(self, db: Session, order_id: str, awb: str) -> dict[str, Any]:
        payload = await self.tracking(awb)
        latest_status = None
        tracking_url = None
        if isinstance(payload, dict):
            data = payload.get("tracking_data") or payload.get("data") or {}
            if isinstance(data, dict):
                latest = data.get("shipment_track")
                if isinstance(latest, list) and latest:
                    latest_status = latest[0].get("current_status") or latest[0].get("status")
                tracking_url = data.get("track_url")
        shipment = upsert_shipment(
            db,
            order_id,
            latest_status=latest_status,
            last_synced_at=datetime.now(timezone.utc),
            tracking_url=tracking_url,
        )
        return snapshot(shipment)
