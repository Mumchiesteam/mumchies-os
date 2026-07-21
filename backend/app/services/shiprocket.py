"""Shiprocket integration for Mumchies OS."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal, InvalidOperation
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.shiprocket import get_shipment, snapshot, upsert_shipment
from app.services.shipment_status import derive_operational_status, has_existing_shipment_evidence


class ShiprocketConfigurationError(RuntimeError):
    """Raised when Shiprocket credentials have not been configured."""


class ShiprocketAPIError(RuntimeError):
    """Raised when Shiprocket rejects a request or returns malformed data."""

    def __init__(self, message: str, *, status_code: int | None = None, safe_details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.safe_details = safe_details or {}


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
    cod_charge: float | None
    total_estimated_shipping_cost: float
    estimated_delivery_days: int | None
    expected_delivery_date: str | None
    rating: float | None
    cod_supported: bool
    prepaid_supported: bool
    mode: str | None
    provider: str = "shiprocket"
    booking_supported: bool = True
    rate_note: str = "Estimated Shiprocket rate"


@dataclass(slots=True)
class BookingEligibilityResult:
    eligible: bool
    missing_requirements: list[str]
    operational_status: str | None
    payment_mode: str | None
    shipment_exists: bool
    shipment_status: str | None
    shipment_snapshot: dict[str, Any] | None = None


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

    @staticmethod
    def _api_error(response: httpx.Response, operation: str) -> "ShiprocketAPIError":
        message = ShiprocketService._safe_message(response)
        try:
            data = response.json()
        except Exception:
            data = {}
        safe_details: dict[str, Any] = {"operation": operation}
        if isinstance(data, dict) and isinstance(data.get("errors"), dict):
            field_errors = data["errors"]
            safe_details["rejected_fields"] = sorted(str(key) for key in field_errors.keys())
            first = next((value for value in field_errors.values() if isinstance(value, (str, list))), None)
            if isinstance(first, list) and first:
                message = str(first[0])
            elif isinstance(first, str):
                message = first
        return ShiprocketAPIError(message, status_code=response.status_code, safe_details=safe_details)

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

    async def pickup_location_details(self) -> dict[str, Any] | None:
        pickup_locations = await self._pickup_locations()
        for location in pickup_locations:
            if str(location.get("pickup_location", "")).strip().lower() == str(self.pickup_location).strip().lower():
                return location
        return None

    async def health(self) -> ShiprocketHealthResult:
        self._validate_configuration()
        token = await self.get_token()
        pickup_location = await self.pickup_location_details()
        pickup_exists = pickup_location is not None
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
        return [self._normalize_serviceability_courier(courier, cod) for courier in available]

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value in (None, "", "null"):
            return None
        try:
            return float(Decimal(str(value)))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value in (None, "", "null"):
            return None
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_expected_delivery_date(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = value.strip()
        for fmt in ("%b %d, %Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
        return candidate

    def _normalize_serviceability_courier(self, courier: dict[str, Any], cod_requested: bool) -> CourierQuote:
        courier_name = str(courier.get("courier_name") or "Unknown courier")
        courier_id = courier.get("courier_company_id") or courier.get("courier_id") or courier.get("id")
        freight = self._to_float(courier.get("freight_charge"))
        if freight is None:
            freight = self._to_float(courier.get("rate"))
        if freight is None:
            freight = self._to_float(courier.get("cost"))
        cod_charge = self._to_float(courier.get("cod_charges"))
        if cod_charge is None:
            cod_charge = self._to_float(courier.get("cod_charge"))
        estimated_delivery_days = self._to_int(courier.get("estimated_delivery_days"))
        expected_delivery_date = self._parse_expected_delivery_date(courier.get("etd") or courier.get("expected_delivery_date"))
        if estimated_delivery_days is None and expected_delivery_date:
            try:
                expected = date.fromisoformat(expected_delivery_date)
                estimated_delivery_days = max((expected - datetime.now(timezone.utc).date()).days, 0)
            except ValueError:
                estimated_delivery_days = None
        rating = self._to_float(courier.get("rating"))
        if rating is None:
            rating = self._to_float(courier.get("pickup_performance"))
        if rating is None:
            rating = self._to_float(courier.get("delivery_performance"))
        mode = None
        if courier.get("is_surface") is True:
            mode = "surface"
        elif courier.get("is_international") is True:
            mode = "international"
        elif courier.get("mode") is not None:
            mode = str(courier.get("mode"))
        elif courier.get("courier_type") is not None:
            mode = str(courier.get("courier_type"))
        cod_supported = bool(courier.get("cod")) or bool(courier.get("cod_charges")) or cod_requested
        prepaid_supported = True
        return CourierQuote(
            courier_id=str(courier_id) if courier_id is not None else None,
            courier_name=courier_name,
            rate=float(freight or 0),
            cod_charge=cod_charge,
            total_estimated_shipping_cost=float((freight or 0) + (cod_charge or 0)),
            estimated_delivery_days=estimated_delivery_days,
            expected_delivery_date=expected_delivery_date,
            rating=rating,
            cod_supported=cod_supported,
            prepaid_supported=prepaid_supported,
            mode=mode,
        )

    @staticmethod
    def _address_postcode(address: Any) -> str | None:
        if not isinstance(address, dict):
            return None
        for key in ("pincode", "postcode", "zip", "postal_code"):
            value = address.get(key)
            if value:
                text = str(value).strip()
                if text:
                    return text
        return None

    @staticmethod
    def _latest_call_result(operations: dict[str, Any] | None) -> str | None:
        if not operations:
            return None
        logs = operations.get("call_logs") or []
        if not logs:
            return None
        result = logs[0].get("result")
        return str(result) if result is not None else None

    def evaluate_booking_eligibility(
        self,
        order: Any,
        operations: dict[str, Any] | None,
        shipment: dict[str, Any] | None = None,
    ) -> BookingEligibilityResult:
        operations = operations or {}
        shipment = shipment or None
        shipping_address = getattr(order, "shipping_address", None)
        corrected_address = operations.get("corrected_address")
        verified_snapshot = operations.get("verified_address_snapshot")
        package_details = operations.get("package_details") or {}
        latest_call = self._latest_call_result(operations)
        # Single authoritative precedence chain - see app/services/shipment_status.py. An order
        # that already has an existing shipment/fulfilment (local or Shopify-native) is never
        # eligible, regardless of call logs or address-verification state.
        status = derive_operational_status(order, operations, shipment)
        payment = "COD" if str(getattr(order, "payment_status", "")).lower() in {"pending", "cod", "partially paid"} else "Prepaid"
        shipment_exists = bool(shipment and (shipment.get("awb") or shipment.get("shipment_id") or shipment.get("shiprocket_order_id")))
        shipment_status = shipment.get("booking_status") if shipment else None

        missing: list[str] = []
        if has_existing_shipment_evidence(order, operations, shipment):
            missing.append("an active shipment or fulfilment already exists for this order")
        delivery_postcode = self._address_postcode(corrected_address or verified_snapshot or shipping_address)
        if not delivery_postcode:
            missing.append("delivery postcode")
        latest_operational_address = corrected_address or verified_snapshot or shipping_address
        if not latest_operational_address:
            missing.append("latest operational address")
        pickup_locations = None
        if self.pickup_location:
            pickup_locations = [self.pickup_location]
        else:
            missing.append("pickup location")
        weight = package_details.get("weight_kg")
        if weight is None or self._to_float(weight) is None or self._to_float(weight) <= 0:
            missing.append("package weight")
        if not package_details.get("length_cm"):
            missing.append("package length")
        if not package_details.get("breadth_cm"):
            missing.append("package breadth")
        if not package_details.get("height_cm"):
            missing.append("package height")

        if payment == "COD":
            if latest_call != "Confirmed":
                missing.append("latest call must be Confirmed")
            if status != "Ready for Booking":
                missing.append("operational status must be Ready for Booking")
        else:
            if not operations.get("address_verified"):
                missing.append("address must be verified")
            if status != "Ready for Booking":
                missing.append("operational status must be Ready for Booking")

        eligible = not missing
        return BookingEligibilityResult(
            eligible=eligible,
            missing_requirements=missing,
            operational_status=status,
            payment_mode=payment,
            shipment_exists=shipment_exists,
            shipment_status=shipment_status,
            shipment_snapshot=shipment,
        )

    def normalize_serviceability(self, couriers: list[dict[str, Any]], cod_requested: bool) -> list[CourierQuote]:
        return [self._normalize_serviceability_courier(courier, cod_requested) for courier in couriers]

    async def create_order(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._post("https://apiv2.shiprocket.in/v1/external/orders/create/adhoc", order_payload)
        if response.status_code >= 400:
            raise self._api_error(response, "create_order")
        return response.json()

    async def assign_courier_and_generate_awb(self, shipment_id: str, courier_id: str) -> dict[str, Any]:
        response = await self._post(
            "https://apiv2.shiprocket.in/v1/external/courier/assign/awb",
            {"shipment_id": shipment_id, "courier_id": courier_id},
        )
        if response.status_code >= 400:
            raise self._api_error(response, "assign_awb")
        return response.json()

    async def find_existing_order(self, channel_order_id: str) -> dict[str, Any] | None:
        response = await self._get(
            "https://apiv2.shiprocket.in/v1/external/orders",
            params={"search": channel_order_id, "per_page": 50},
        )
        if response.status_code >= 400:
            raise self._api_error(response, "find_order")
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return None
        return next((row for row in rows if str(row.get("channel_order_id") or "") == channel_order_id), None)

    @staticmethod
    def _upstream_shipment(order: dict[str, Any]) -> tuple[str | None, str | None]:
        shipments = order.get("shipments") or []
        shipment = shipments[0] if isinstance(shipments, list) and shipments else {}
        shipment_id = shipment.get("id") or order.get("shipment_id")
        awb = shipment.get("awb") or shipment.get("awb_code") or order.get("awb_code")
        return (str(shipment_id) if shipment_id is not None else None, str(awb) if awb else None)

    @staticmethod
    def _nested_value(payload: dict[str, Any] | None, *keys: str) -> Any:
        current: Any = payload or {}
        for _ in range(4):
            if isinstance(current, dict):
                for key in keys:
                    if current.get(key) not in (None, ""):
                        return current[key]
                current = current.get("data") or current.get("response")
            else:
                break
        return None

    @staticmethod
    def _parse_upstream_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d %b %Y, %I:%M %p", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                parsed = datetime.strptime(value.strip(), fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    async def reconcile_existing_shipment(
        self,
        db: Session,
        local_order_id: str,
        channel_order_id: str,
        expected_shipment_id: str | None = None,
    ) -> dict[str, Any]:
        upstream = await self.find_existing_order(channel_order_id)
        if not upstream:
            raise ShiprocketAPIError("Shiprocket order was not found.", safe_details={"operation": "refresh_shipment"})
        shipments = upstream.get("shipments") or []
        if not isinstance(shipments, list) or not shipments:
            raise ShiprocketAPIError("Shiprocket order has no shipment.", safe_details={"operation": "refresh_shipment"})
        shipment = next((item for item in shipments if str(item.get("id")) == str(expected_shipment_id)), shipments[0])
        shipment_id = str(shipment.get("id")) if shipment.get("id") is not None else expected_shipment_id
        awb = shipment.get("awb") or shipment.get("awb_code")
        courier_name = shipment.get("courier") or shipment.get("sr_courier_name") or shipment.get("courier_name")
        courier_id = shipment.get("courier_id") or shipment.get("courier_company_id")
        upstream_status = str(upstream.get("status") or shipment.get("status_name") or shipment.get("status") or "").strip()
        booked_at = self._parse_upstream_datetime(shipment.get("awb_assign_date"))
        tracking_url = None
        latest_status = upstream_status or "AWB pending"
        if awb:
            try:
                tracking_payload = await self.tracking(str(awb))
                tracking_data = tracking_payload.get("tracking_data") or tracking_payload.get("data") or {}
                if isinstance(tracking_data, dict):
                    tracking_url = tracking_data.get("track_url") or tracking_data.get("tracking_url")
                    tracks = tracking_data.get("shipment_track") or []
                    if isinstance(tracks, list) and tracks:
                        latest_status = tracks[0].get("current_status") or tracks[0].get("status") or latest_status
            except ShiprocketAPIError:
                pass
        persisted = upsert_shipment(
            db,
            local_order_id,
            provider="shiprocket",
            provider_order_id=channel_order_id,
            shiprocket_order_id=str(upstream.get("id")) if upstream.get("id") is not None else None,
            shipment_id=shipment_id,
            awb=str(awb) if awb else None,
            courier_name=str(courier_name) if courier_name else None,
            courier_id=str(courier_id) if courier_id is not None else None,
            booking_status="booked" if awb else "pending_awb",
            booked_at=booked_at,
            latest_status=str(latest_status),
            last_synced_at=datetime.now(timezone.utc),
            tracking_url=str(tracking_url) if tracking_url else None,
            label_url=f"/api/v1/orders/{local_order_id}/shipping-label" if awb else None,
        )
        return snapshot(persisted)

    async def create_shipment(self, db: Session, order_id: str, order_payload: dict[str, Any], courier_id: str | None = None) -> dict[str, Any]:
        created_order = await self.create_order(order_payload)
        order_data = created_order.get("order_id") or created_order.get("data", {}).get("order_id")
        shipment_id = created_order.get("shipment_id") or created_order.get("data", {}).get("shipment_id")
        awb = created_order.get("awb_code") or created_order.get("data", {}).get("awb_code")
        selected_courier_id = courier_id or created_order.get("courier_company_id") or created_order.get("data", {}).get("courier_company_id")
        courier_name = created_order.get("courier_name") or created_order.get("data", {}).get("courier_name")
        persisted = upsert_shipment(
            db,
            order_id,
            provider="shiprocket",
            provider_order_id=str(order_payload.get("order_id") or ""),
            shiprocket_order_id=str(order_data) if order_data is not None else None,
            shipment_id=str(shipment_id) if shipment_id is not None else None,
            courier_id=str(selected_courier_id) if selected_courier_id is not None else None,
            booking_status="pending_awb",
            latest_status="order_created",
            last_synced_at=datetime.now(timezone.utc),
        )
        assign_response = None
        if shipment_id and selected_courier_id:
            try:
                assign_response = await self.assign_courier_and_generate_awb(str(shipment_id), str(selected_courier_id))
            except ShiprocketAPIError:
                upsert_shipment(db, order_id, booking_status="awb_failed", latest_status="AWB assignment failed")
                raise
            awb = awb or self._nested_value(assign_response, "awb_code", "awb")
            courier_name = courier_name or self._nested_value(assign_response, "courier_name", "courier")
        persisted = upsert_shipment(
            db,
            order_id,
            provider="shiprocket",
            shiprocket_order_id=str(order_data) if order_data is not None else None,
            shipment_id=str(shipment_id) if shipment_id is not None else None,
            awb=str(awb) if awb is not None else None,
            courier_name=str(courier_name) if courier_name is not None else None,
            courier_id=str(selected_courier_id) if selected_courier_id is not None else None,
            booking_status="booked" if awb else "pending_awb",
            booked_at=datetime.now(timezone.utc) if awb else None,
            latest_status="booked" if awb else "AWB pending",
            last_synced_at=datetime.now(timezone.utc),
            tracking_url=created_order.get("tracking_url") or created_order.get("data", {}).get("tracking_url"),
            label_url=created_order.get("label_url") or created_order.get("data", {}).get("label_url"),
        )
        if not awb and shipment_id:
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(0.5)
                reconciled = await self.reconcile_existing_shipment(db, order_id, str(order_payload.get("order_id") or ""), str(shipment_id))
                if reconciled.get("awb"):
                    return {"shipment": reconciled, "shiprocket": created_order, "assignment": assign_response}
        return {"shipment": snapshot(persisted), "shiprocket": created_order, "assignment": assign_response}

    async def book_order_shipment(
        self,
        db: Session,
        order_id: str,
        order_payload: dict[str, Any],
        courier_id: str | None = None,
        package_details: dict[str, Any] | None = None,
        courier_name: str | None = None,
    ) -> dict[str, Any]:
        existing = get_shipment(db, order_id)
        if existing and (existing.awb or existing.shipment_id or existing.shiprocket_order_id):
            if existing.awb:
                return {"shipment": snapshot(existing), "existing": True}
            if existing.shipment_id and courier_id:
                assignment = await self.assign_courier_and_generate_awb(existing.shipment_id, courier_id)
                awb = self._nested_value(assignment, "awb_code", "awb")
                persisted = upsert_shipment(
                    db, order_id, awb=str(awb) if awb else None,
                    booking_status="booked" if awb else "pending_awb",
                    booked_at=datetime.now(timezone.utc) if awb else None,
                    latest_status="booked" if awb else "AWB pending",
                )
                return {"shipment": snapshot(persisted), "existing": True, "assignment": assignment}

        channel_order_id = str(order_payload.get("order_id") or "")
        upstream = await self.find_existing_order(channel_order_id)
        if upstream:
            upstream_status = str(upstream.get("status") or "").upper()
            shipment_id, awb = self._upstream_shipment(upstream)
            if upstream_status in {"CANCELED", "CANCELLED"}:
                raise ShiprocketAPIError(
                    "The existing Shiprocket order is canceled and cannot be assigned. Restore or recreate it in Shiprocket before booking.",
                    safe_details={"operation": "reuse_order", "shiprocket_status": upstream_status},
                )
            persisted = upsert_shipment(
                db, order_id, provider="shiprocket", provider_order_id=channel_order_id,
                shiprocket_order_id=str(upstream.get("id") or "") or None,
                shipment_id=shipment_id, awb=awb, booking_status="booked" if awb else "pending_awb",
                latest_status=upstream_status or "order_found", last_synced_at=datetime.now(timezone.utc),
            )
            if awb:
                return {"shipment": snapshot(persisted), "existing": True}
            if not shipment_id or not courier_id:
                raise ShiprocketAPIError("The existing Shiprocket order has no assignable shipment.", safe_details={"operation": "reuse_order"})
            assignment = await self.assign_courier_and_generate_awb(shipment_id, courier_id)
            assigned_awb = self._nested_value(assignment, "awb_code", "awb")
            persisted = upsert_shipment(
                db, order_id, awb=str(assigned_awb) if assigned_awb else None,
                booking_status="booked" if assigned_awb else "pending_awb",
                booked_at=datetime.now(timezone.utc) if assigned_awb else None,
                latest_status="booked" if assigned_awb else "AWB pending",
            )
            return {"shipment": snapshot(persisted), "existing": True, "assignment": assignment}

        result = await self.create_shipment(db, order_id, order_payload, courier_id)
        persisted = upsert_shipment(
            db,
            order_id,
            package_weight_kg=self._to_float((package_details or {}).get("weight_kg")),
            package_length_cm=self._to_float((package_details or {}).get("length_cm")),
            package_breadth_cm=self._to_float((package_details or {}).get("breadth_cm")),
            package_height_cm=self._to_float((package_details or {}).get("height_cm")),
            selected_courier_id=str(courier_id) if courier_id is not None else None,
            selected_courier_name=courier_name or result.get("shipment", {}).get("courier_name"),
        )
        result["shipment"] = snapshot(persisted)
        return result

    async def tracking(self, awb: str) -> dict[str, Any]:
        response = await self._get(f"https://apiv2.shiprocket.in/v1/external/courier/track/awb/{awb}")
        if response.status_code >= 400:
            raise ShiprocketAPIError(self._safe_message(response))
        return response.json()

    async def fetch_label(self, shipment_id: str) -> httpx.Response:
        response = await self._post(
            "https://apiv2.shiprocket.in/v1/external/courier/generate/label",
            {"shipment_id": [int(shipment_id)]},
        )
        if response.status_code >= 400:
            raise self._api_error(response, "generate_label")
        payload = response.json()
        label_url = payload.get("label_url") or payload.get("data", {}).get("label_url")
        if not isinstance(label_url, str) or not label_url.startswith("https://"):
            raise ShiprocketAPIError("Shipping label is not yet available.", safe_details={"operation": "generate_label"})
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            pdf_response = await client.get(label_url)
        if pdf_response.status_code >= 400:
            raise ShiprocketAPIError("Shipping label PDF could not be downloaded.", status_code=pdf_response.status_code, safe_details={"operation": "download_label"})
        return pdf_response

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
