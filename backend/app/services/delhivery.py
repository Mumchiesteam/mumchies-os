from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.repositories.shiprocket import get_shipment, snapshot, upsert_shipment


class DelhiveryError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, partial: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.partial = partial or {}


@dataclass(slots=True)
class DelhiveryQuote:
    courier_id: str
    courier_name: str
    rate: float
    cod_charge: float | None
    total_estimated_shipping_cost: float
    estimated_delivery_days: int | None
    expected_delivery_date: str | None
    rating: float | None
    cod_supported: bool
    prepaid_supported: bool
    mode: str
    provider: str = "delhivery"
    booking_supported: bool = False
    rate_note: str = "Estimated direct-account rate"


class DelhiveryService:
    base_url = "https://track.delhivery.com"
    _official_label_hosts = {
        "track.delhivery.com",
        "express-hq-prod.s3.ap-south-1.amazonaws.com",
    }
    _maximum_label_bytes = 20 * 1024 * 1024

    def __init__(self, token: str | None = None, pickup: str | None = None) -> None:
        self.token = token or settings.delhivery_token
        self.pickup = pickup or settings.delhivery_pickup

    @property
    def configured(self) -> bool:
        """Direct booking is available whenever the required account configuration exists."""
        return bool(str(self.token or "").strip() and str(self.pickup or "").strip())

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise DelhiveryError("Delhivery is not configured.")
        return {"Authorization": f"Token {self.token}", "Accept": "application/json"}

    async def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}{path}", params=params, headers=self._headers())
        if response.status_code >= 400:
            raise DelhiveryError(self._safe_error(response), status_code=response.status_code)
        return response

    async def _post(self, path: str, *, data: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}{path}", data=data, json=json_body, headers=self._headers()
            )
        if response.status_code >= 400:
            raise DelhiveryError(self._safe_error(response), status_code=response.status_code)
        return response

    @staticmethod
    def _safe_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            return f"Delhivery request failed ({response.status_code})."
        if isinstance(payload, dict):
            message = payload.get("error") or payload.get("message") or payload.get("rmk")
            if message:
                return f"Delhivery rejected the request: {message}"
        return f"Delhivery request failed ({response.status_code})."

    async def serviceability(self, pickup_postcode: str, delivery_postcode: str, weight_kg: float, cod: bool) -> list[DelhiveryQuote]:
        pin = await self._get("/c/api/pin-codes/json/", {"filter_codes": delivery_postcode})
        delivery_codes = pin.json().get("delivery_codes") or []
        if not delivery_codes:
            return []
        postal = (delivery_codes[0].get("postal_code") or {})
        if cod and str(postal.get("cod") or "").upper() != "Y":
            return []
        if not cod and str(postal.get("pre_paid") or postal.get("prepaid") or "").upper() != "Y":
            return []

        response = await self._get(
            "/api/kinko/v1/invoice/charges/.json",
            {
                "md": "S",
                "ss": "Delivered",
                "o_pin": pickup_postcode,
                "d_pin": delivery_postcode,
                "cgm": max(round(weight_kg * 1000), 1),
                "pt": "COD" if cod else "Pre-paid",
            },
        )
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("data") or payload.get("charges") or [payload]
        quotes: list[DelhiveryQuote] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            total = self._number(row.get("total_amount") or row.get("gross_amount") or row.get("total") or row.get("freight"))
            if total is None:
                continue
            cod_charge = self._number(row.get("charge_COD") or row.get("cod_charge"))
            freight = max(total - (cod_charge or 0), 0)
            mode = str(row.get("mode") or row.get("md") or "Surface")
            tat = self._integer(row.get("tat") or row.get("estimated_delivery_days"))
            quotes.append(DelhiveryQuote(
                courier_id=f"delhivery:{mode.lower()}", courier_name=f"Delhivery {mode}", rate=freight,
                cod_charge=cod_charge, total_estimated_shipping_cost=total, estimated_delivery_days=tat,
                expected_delivery_date=None, rating=None, cod_supported=True, prepaid_supported=True, mode=mode.lower(),
                booking_supported=self.configured,
                rate_note="Estimated direct-account rate",
            ))
        return quotes

    async def fetch_waybill(self) -> str:
        response = await self._get("/waybill/api/bulk/json/", {"count": 1})
        payload = response.json()
        value = payload.get("waybill") or payload.get("waybills") or payload.get("data")
        if isinstance(value, list):
            value = value[0] if value else None
        if not value:
            raise DelhiveryError("Delhivery did not return a waybill.")
        return str(value)

    async def create_shipment(self, shipment: dict[str, Any]) -> dict[str, Any]:
        """Manifest one B2C shipment and let Delhivery assign the waybill atomically."""
        response = await self._post(
            "/api/cmu/create.json",
            data={"format": "json", "data": json.dumps({"shipments": [shipment], "pickup_location": {"name": self.pickup}})},
        )
        payload = response.json()
        packages = payload.get("packages") or []
        package = packages[0] if packages else {}
        waybill = package.get("waybill") or package.get("awb")
        if not payload.get("success", bool(package)) or package.get("status") in {"Fail", "Failure"}:
            raise DelhiveryError(
                str(package.get("remarks") or payload.get("rmk") or "Delhivery rejected the shipment."),
                partial={"waybill": str(waybill) if waybill else None, "status": package.get("status")},
            )
        if not waybill:
            raise DelhiveryError("Delhivery accepted the shipment but did not return a waybill.", partial={"status": package.get("status")})
        return {"waybill": str(waybill), "package": package, "response": payload}

    @staticmethod
    def _tracking_packages(payload: dict[str, Any]) -> list[dict[str, Any]]:
        values = payload.get("ShipmentData") or payload.get("shipments") or payload.get("data") or []
        return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []

    @classmethod
    def normalize_tracking(cls, payload: dict[str, Any]) -> dict[str, Any] | None:
        packages = cls._tracking_packages(payload)
        if not packages:
            return None
        wrapper = packages[0]
        shipment = wrapper.get("Shipment") if isinstance(wrapper.get("Shipment"), dict) else wrapper
        status_block = shipment.get("Status") if isinstance(shipment.get("Status"), dict) else {}
        scans = shipment.get("Scans") if isinstance(shipment.get("Scans"), list) else []
        latest_scan = scans[0].get("ScanDetail", {}) if scans and isinstance(scans[0], dict) else {}
        waybill = shipment.get("AWB") or shipment.get("Waybill") or shipment.get("waybill")
        status = status_block.get("Status") or latest_scan.get("Scan") or shipment.get("Status")
        reference = shipment.get("ReferenceNo") or shipment.get("OrderID") or shipment.get("order")
        expected_delivery_date = shipment.get("ExpectedDeliveryDate") or shipment.get("ExpectedDeliveryDateTime") or shipment.get("EDD")
        status_date = status_block.get("StatusDateTime") or status_block.get("StatusDate") or latest_scan.get("ScanDateTime")
        delivered_at = cls._parse_datetime(status_date) if str(status or "").casefold() == "delivered" else None
        return {
            "waybill": str(waybill) if waybill else None,
            "reference": str(reference) if reference else None,
            "status": str(status) if status else "Manifested",
            "tracking_url": f"https://www.delhivery.com/track/package/{waybill}" if waybill else None,
            "expected_delivery_date": str(expected_delivery_date) if expected_delivery_date else None,
            "delivered_at": delivered_at,
            "raw": payload,
        }

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    async def find_by_order_number(self, order_number: str) -> dict[str, Any] | None:
        response = await self._get("/api/v1/packages/json/", {"ref_ids": order_number})
        return self.normalize_tracking(response.json())

    async def tracking(self, waybill: str) -> dict[str, Any]:
        response = await self._get("/api/v1/packages/json/", {"waybill": waybill})
        normalized = self.normalize_tracking(response.json())
        if normalized is None:
            raise DelhiveryError("Delhivery did not return tracking data for this waybill.")
        return normalized

    @classmethod
    def _is_official_label_url(cls, value: str) -> bool:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or host not in cls._official_label_hosts:
            return False
        if host.endswith("amazonaws.com"):
            return parsed.path.startswith("/packing-slip/") and parsed.path.casefold().endswith(".pdf")
        return True

    @classmethod
    def _official_pdf_url(cls, value: Any, parent_key: str = "") -> str | None:
        """Find only explicitly label/document-related URLs in a provider JSON response."""
        if isinstance(value, dict):
            preferred = ("pdf_download_link", "pdf_url", "label_url", "document_url", "download_url")
            for key in preferred:
                candidate = value.get(key)
                if isinstance(candidate, str) and cls._is_official_label_url(candidate):
                    return candidate
            for key, nested in value.items():
                found = cls._official_pdf_url(nested, str(key))
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = cls._official_pdf_url(nested, parent_key)
                if found:
                    return found
        elif isinstance(value, str):
            key = parent_key.casefold()
            if any(marker in key for marker in ("pdf", "label", "document", "download")) and cls._is_official_label_url(value):
                return value
        return None

    @classmethod
    def _validate_pdf_response(cls, response: httpx.Response) -> httpx.Response:
        if len(response.content) > cls._maximum_label_bytes:
            raise DelhiveryError("Delhivery's official PDF label exceeds the allowed download size.")
        if not response.content.startswith(b"%PDF-"):
            raise DelhiveryError("Delhivery did not return a valid official PDF label.")
        return response

    async def label(self, waybill: str) -> httpx.Response:
        """Resolve Delhivery's official label without modifying or re-rendering its bytes."""
        if not waybill:
            raise DelhiveryError("A Delhivery AWB is required to retrieve the official label.")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.get(
                f"{self.base_url}/api/p/packing_slip",
                params={"wbns": waybill, "pdf": "True"},
                headers=self._headers(),
            )
        if response.status_code in {401, 403}:
            raise DelhiveryError(
                "Official Delhivery PDF label is not enabled for this account. Contact your Delhivery POC.",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise DelhiveryError(self._safe_error(response), status_code=response.status_code)
        if response.content.startswith(b"%PDF-"):
            return self._validate_pdf_response(response)

        try:
            payload = response.json()
        except Exception as error:
            raise DelhiveryError("Delhivery returned neither an official PDF nor a PDF download URL.") from error
        packages = payload.get("packages") if isinstance(payload, dict) else None
        if isinstance(packages, list) and not packages:
            raise DelhiveryError("Delhivery could not generate a label: the AWB is invalid, unmanifested, or was not found.")
        pdf_url = self._official_pdf_url(payload)
        if not pdf_url:
            raise DelhiveryError("Official Delhivery PDF label is not enabled for this account. Contact your Delhivery POC.")

        # Never forward the Delhivery token to the provider-hosted object URL.
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            pdf_response = await client.get(pdf_url, headers={"Accept": "application/pdf"})
        if pdf_response.status_code >= 400:
            raise DelhiveryError("Delhivery's official PDF label could not be downloaded.", status_code=pdf_response.status_code)
        return self._validate_pdf_response(pdf_response)

    async def cancel(self, waybill: str) -> dict[str, Any]:
        response = await self._post("/api/p/edit", json_body={"waybill": waybill, "cancellation": "true"})
        return response.json()

    async def reconcile(self, db, order_id: str, *, order_number: str, waybill: str | None = None) -> dict[str, Any]:
        tracked = await self.tracking(waybill) if waybill else await self.find_by_order_number(order_number)
        if tracked is None:
            raise DelhiveryError("No existing Delhivery shipment was found for this order.")
        resolved_waybill = tracked.get("waybill") or waybill
        persisted = upsert_shipment(
            db, order_id,
            provider="delhivery", provider_order_id=order_number,
            shipment_id=str(resolved_waybill) if resolved_waybill else None,
            awb=str(resolved_waybill) if resolved_waybill else None,
            courier_name="Delhivery Surface", courier_id="delhivery:surface",
            booking_status="booked" if resolved_waybill else "manifested_pending_waybill",
            booked_at=datetime.now(timezone.utc) if resolved_waybill else None,
            latest_status=tracked.get("status") or "Manifested",
            last_synced_at=datetime.now(timezone.utc),
            tracking_url=tracked.get("tracking_url"),
            label_url=None,
            expected_delivery_date=tracked.get("expected_delivery_date"),
            delivered_at=tracked.get("delivered_at"),
        )
        return snapshot(persisted)

    async def book_order_shipment(
        self, db, order_id: str, order_number: str, shipment_payload: dict[str, Any],
        package_details: dict[str, Any], courier_id: str, courier_name: str,
    ) -> dict[str, Any]:
        existing = get_shipment(db, order_id)
        if existing and (existing.awb or existing.shipment_id or existing.provider_order_id):
            if existing.provider and existing.provider != "delhivery":
                raise DelhiveryError(f"Order is already booked with {existing.provider}.")
            if existing.awb:
                return {"shipment": snapshot(existing), "existing": True}
            try:
                reconciled = await self.reconcile(db, order_id, order_number=existing.provider_order_id or order_number, waybill=existing.shipment_id)
                return {"shipment": reconciled, "existing": True}
            except (DelhiveryError, httpx.HTTPError) as error:
                raise DelhiveryError(
                    "A previous Delhivery booking has an uncertain outcome. Refresh/reconcile it before retrying.",
                    partial={"provider_order_id": existing.provider_order_id, "status": existing.booking_status},
                ) from error

        upstream = await self.find_by_order_number(order_number)
        if upstream and upstream.get("waybill"):
            reconciled = await self.reconcile(db, order_id, order_number=order_number, waybill=str(upstream["waybill"]))
            return {"shipment": reconciled, "existing": True}

        try:
            created = await self.create_shipment(shipment_payload)
        except httpx.HTTPError as error:
            upsert_shipment(
                db, order_id, provider="delhivery", provider_order_id=order_number,
                courier_name=courier_name, courier_id=courier_id,
                booking_status="manifest_unknown", latest_status="Provider response uncertain",
                last_synced_at=datetime.now(timezone.utc),
                package_weight_kg=self._number(package_details.get("weight_kg")),
                package_length_cm=self._number(package_details.get("length_cm")),
                package_breadth_cm=self._number(package_details.get("breadth_cm")),
                package_height_cm=self._number(package_details.get("height_cm")),
                selected_courier_id=courier_id, selected_courier_name=courier_name,
            )
            try:
                reconciled = await self.reconcile(db, order_id, order_number=order_number)
                return {"shipment": reconciled, "existing": True, "reconciled_after_timeout": True}
            except (DelhiveryError, httpx.HTTPError):
                raise DelhiveryError(
                    "Delhivery did not confirm the booking response. The outcome is uncertain; refresh before retrying.",
                    partial={"provider_order_id": order_number, "status": "manifest_unknown"},
                ) from error
        except DelhiveryError as error:
            if error.partial:
                partial_waybill = error.partial.get("waybill")
                upsert_shipment(
                    db, order_id, provider="delhivery", provider_order_id=order_number,
                    shipment_id=partial_waybill, awb=partial_waybill,
                    courier_name=courier_name, courier_id=courier_id,
                    booking_status="manifest_partial", latest_status=str(error.partial.get("status") or "Provider response incomplete"),
                    last_synced_at=datetime.now(timezone.utc),
                )
                try:
                    reconciled = await self.reconcile(db, order_id, order_number=order_number, waybill=str(partial_waybill) if partial_waybill else None)
                    return {"shipment": reconciled, "existing": True, "reconciled_after_partial": True}
                except (DelhiveryError, httpx.HTTPError):
                    pass
            raise

        waybill = created["waybill"]
        package = created.get("package") or {}
        persisted = upsert_shipment(
            db, order_id,
            provider="delhivery", provider_order_id=order_number,
            shipment_id=waybill, awb=waybill,
            courier_name=courier_name or "Delhivery Surface", courier_id=courier_id,
            booking_status="booked", booked_at=datetime.now(timezone.utc),
            latest_status=str(package.get("status") or "Manifested"), last_synced_at=datetime.now(timezone.utc),
            tracking_url=f"https://www.delhivery.com/track/package/{waybill}",
            label_url=None,
            package_weight_kg=self._number(package_details.get("weight_kg")),
            package_length_cm=self._number(package_details.get("length_cm")),
            package_breadth_cm=self._number(package_details.get("breadth_cm")),
            package_height_cm=self._number(package_details.get("height_cm")),
            selected_courier_id=courier_id, selected_courier_name=courier_name,
        )
        return {"shipment": snapshot(persisted), "existing": False, "delhivery": created["response"]}

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            return int(float(value)) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None


def shadowfax_zone_d_quote(cod: bool) -> dict[str, Any]:
    return {
        "courier_id": "shadowfax:manual-zone-d",
        "courier_name": "Shadowfax 360 Manual",
        "rate": 59.0,
        "cod_charge": 0.0 if cod else None,
        "total_estimated_shipping_cost": 59.0,
        "estimated_delivery_days": None,
        "expected_delivery_date": None,
        "rating": None,
        "cod_supported": True,
        "prepaid_supported": True,
        "mode": "surface",
        "provider": "shadowfax",
        "booking_supported": False,
        "rate_note": "Zone D fallback; GST extra; booking is manual",
    }
