from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Protocol

from app.core.config import settings
from app.services.courier_platform.base import CourierAdapter, ProviderConfigurationError, ProviderError
from app.services.courier_platform.models import (
    BookingConfidence, BookingResult, CancellationResult, LabelFormat, LabelResult,
    NormalizedShipmentStatus, ProviderCapabilities, QuoteResult, ReconciliationStatus, ServiceabilityResult, TrackingResult,
)
from app.services.courier_platform.status import is_terminal, normalize_status


class ShadowfaxTransport(Protocol):
    """Official HTTP boundary. Implement only from the Shadowfax Forward Integration spec."""
    async def authenticate(self) -> bool: ...
    async def serviceability(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def create_booking(self, request: dict[str, Any]) -> dict[str, Any]: ...
    async def find_booking(self, merchant_order_id: str) -> dict[str, Any] | None: ...
    async def track_shipment(self, shipment: dict[str, Any]) -> dict[str, Any]: ...
    async def cancel_booking(self, shipment: dict[str, Any]) -> dict[str, Any]: ...
    async def download_label(self, shipment: dict[str, Any]) -> tuple[bytes, str, str | None]: ...


class LegacyAdapter(CourierAdapter):
    """Adapter for established providers while their proven HTTP clients remain unchanged."""
    def __init__(self, provider: str, *, configured: Callable[[], bool], authenticate: Callable[[], Awaitable[bool]],
                 serviceability: Callable[[dict[str, Any]], Awaitable[ServiceabilityResult]],
                 booking: Callable[[dict[str, Any]], Awaitable[BookingResult]],
                 reconcile: Callable[[str], Awaitable[BookingResult | None]],
                 tracking: Callable[[dict[str, Any]], Awaitable[TrackingResult]],
                 cancellation: Callable[[dict[str, Any]], Awaitable[CancellationResult]],
                 label: Callable[[dict[str, Any]], Awaitable[LabelResult]], capabilities: ProviderCapabilities) -> None:
        self.provider = provider
        self._configured, self._authenticate = configured, authenticate
        self._serviceability, self._booking, self._reconcile = serviceability, booking, reconcile
        self._tracking, self._cancellation, self._label = tracking, cancellation, label
        self.capabilities = capabilities

    @property
    def configured(self) -> bool: return self._configured()
    async def authenticate(self) -> bool: return await self._authenticate()
    async def serviceability(self, request: dict[str, Any]) -> ServiceabilityResult: return await self._serviceability(request)
    async def create_booking(self, request: dict[str, Any]) -> BookingResult: return await self._booking(request)
    async def reconcile_booking(self, merchant_order_id: str) -> BookingResult | None: return await self._reconcile(merchant_order_id)
    async def track_shipment(self, shipment: dict[str, Any]) -> TrackingResult: return await self._tracking(shipment)
    async def cancel_booking(self, shipment: dict[str, Any]) -> CancellationResult: return await self._cancellation(shipment)
    async def download_label(self, shipment: dict[str, Any]) -> LabelResult: return await self._label(shipment)


class ShiprocketAdapter(CourierAdapter):
    provider = "shiprocket"
    capabilities = ProviderCapabilities(serviceability=True, booking=True, tracking=True, cancellation=True, labels=True, polling=True)

    @property
    def configured(self) -> bool:
        return bool(settings.shiprocket_email and settings.shiprocket_password and settings.shiprocket_pickup)

    async def authenticate(self) -> bool:
        from app.services.shiprocket import ShiprocketService
        return bool((await ShiprocketService().health()).authenticated)

    async def serviceability(self, request: dict[str, Any]) -> ServiceabilityResult:
        from app.services.shiprocket import ShiprocketService
        quotes = await ShiprocketService().serviceability(str(request["pickup_pincode"]), str(request["delivery_pincode"]), float(request["weight_kg"]), str(request.get("payment_mode")) == "COD")
        normalized = [QuoteResult(provider=self.provider, service_id=str(q.courier_id or q.courier_name), courier_name=q.courier_name, serviceable=True, charges=q.total_estimated_shipping_cost, cod_charge=q.cod_charge, estimated_delivery_days=q.estimated_delivery_days, expected_delivery_date=q.expected_delivery_date, service_type=q.mode) for q in quotes]
        return ServiceabilityResult(provider=self.provider, serviceable=bool(normalized), quotes=normalized, reason=None if normalized else "No Shiprocket service available.")

    async def create_booking(self, request: dict[str, Any]) -> BookingResult:
        callback = request.get("legacy_booking")
        if not callable(callback):
            raise ProviderError("Shiprocket booking requires the established route context.", provider=self.provider, operation="booking")
        return await callback()

    async def reconcile_booking(self, merchant_order_id: str) -> BookingResult | None:
        from app.services.shiprocket import ShiprocketService
        raw = await ShiprocketService().find_existing_order(merchant_order_id)
        if not raw: return None
        shipment_id, awb = ShiprocketService._upstream_shipment(raw)
        return BookingResult(provider=self.provider, provider_order_id=str(raw.get("id") or "") or None, shipment_id=shipment_id, awb=awb, status=normalize_status(raw.get("status") or ("booked" if awb else "created")), existing=True, raw_response=self.sanitize(raw))

    async def track_shipment(self, shipment: dict[str, Any]) -> TrackingResult:
        from app.services.shiprocket import ShiprocketService
        if not shipment.get("awb"): raise ProviderError("Shipment has no AWB.", provider=self.provider, operation="tracking")
        raw = await ShiprocketService().tracking(str(shipment["awb"]))
        data = raw.get("tracking_data") or raw.get("data") or {}
        tracks = data.get("shipment_track") or [] if isinstance(data, dict) else []
        latest = tracks[0] if isinstance(tracks, list) and tracks else {}
        provider_status = latest.get("current_status") or latest.get("status") or data.get("shipment_status")
        status = normalize_status(provider_status)
        return TrackingResult(provider=self.provider, status=status, provider_status=str(provider_status or "") or None, latest_scan=str(latest.get("location") or latest.get("activity") or "") or None, latest_tracking_at=None, tracking_url=data.get("track_url") or data.get("tracking_url"), terminal=is_terminal(status), raw_response=self.sanitize(raw))

    async def cancel_booking(self, shipment: dict[str, Any]) -> CancellationResult:
        raise ProviderError("Shiprocket shipment cancellation remains protected by its existing preflight workflow.", provider=self.provider, operation="cancellation")

    async def download_label(self, shipment: dict[str, Any]) -> LabelResult:
        from app.services.shiprocket import ShiprocketService
        if not shipment.get("shipment_id"): raise ProviderError("Shipment ID is required for a label.", provider=self.provider, operation="label")
        response = await ShiprocketService().fetch_label(str(shipment["shipment_id"]))
        return LabelResult(provider=self.provider, content=response.content, format=LabelFormat.PDF, content_type="application/pdf")


class DelhiveryAdapter(CourierAdapter):
    provider = "delhivery"
    capabilities = ProviderCapabilities(serviceability=True, booking=True, tracking=True, cancellation=True, labels=True, polling=True)

    @property
    def configured(self) -> bool:
        from app.services.delhivery import DelhiveryService
        return DelhiveryService().configured

    async def authenticate(self) -> bool: return self.configured

    async def serviceability(self, request: dict[str, Any]) -> ServiceabilityResult:
        from app.services.delhivery import DelhiveryService
        quotes = await DelhiveryService().serviceability(str(request["pickup_pincode"]), str(request["delivery_pincode"]), float(request["weight_kg"]), str(request.get("payment_mode")) == "COD")
        normalized = [QuoteResult(provider=self.provider, service_id=str(q.courier_id or q.courier_name), courier_name=q.courier_name, serviceable=bool(q.booking_supported), charges=q.total_estimated_shipping_cost, cod_charge=q.cod_charge, estimated_delivery_days=q.estimated_delivery_days, expected_delivery_date=q.expected_delivery_date, service_type=q.mode, reason=q.rate_note) for q in quotes]
        return ServiceabilityResult(provider=self.provider, serviceable=any(q.serviceable for q in normalized), quotes=normalized)

    async def create_booking(self, request: dict[str, Any]) -> BookingResult:
        callback = request.get("legacy_booking")
        if not callable(callback): raise ProviderError("Delhivery booking requires the established route context.", provider=self.provider, operation="booking")
        return await callback()

    async def reconcile_booking(self, merchant_order_id: str) -> BookingResult | None:
        from app.services.delhivery import DelhiveryService
        raw = await DelhiveryService().find_by_order_number(merchant_order_id)
        if not raw: return None
        awb = str(raw.get("waybill") or "") or None
        return BookingResult(provider=self.provider, provider_order_id=merchant_order_id, shipment_id=awb, awb=awb, tracking_url=raw.get("tracking_url"), service="Delhivery Surface", status=normalize_status(raw.get("status") or "booked"), existing=True, raw_response=self.sanitize(raw))

    async def track_shipment(self, shipment: dict[str, Any]) -> TrackingResult:
        from app.services.delhivery import DelhiveryService
        if not shipment.get("awb"): raise ProviderError("Shipment has no AWB.", provider=self.provider, operation="tracking")
        raw = await DelhiveryService().tracking(str(shipment["awb"]))
        status = normalize_status(raw.get("status"))
        return TrackingResult(provider=self.provider, status=status, provider_status=str(raw.get("status") or "") or None, latest_scan=str(raw.get("location") or "") or None, latest_tracking_at=None, tracking_url=raw.get("tracking_url"), terminal=is_terminal(status), raw_response=self.sanitize(raw))

    async def cancel_booking(self, shipment: dict[str, Any]) -> CancellationResult:
        from app.services.delhivery import DelhiveryService
        status = normalize_status(shipment.get("normalized_status") or shipment.get("latest_status"))
        if status in {NormalizedShipmentStatus.PICKED_UP, NormalizedShipmentStatus.IN_TRANSIT, NormalizedShipmentStatus.OUT_FOR_DELIVERY, NormalizedShipmentStatus.DELIVERED, NormalizedShipmentStatus.RTO}:
            raise ProviderError("Shipped, delivered, or RTO Delhivery shipments require a protected workflow.", provider=self.provider, operation="cancellation")
        raw = await DelhiveryService().cancel(str(shipment.get("awb") or ""))
        return CancellationResult(provider=self.provider, status="cancelled", cancelled=True, message="Delhivery cancellation accepted.", raw_response=self.sanitize(raw))

    async def download_label(self, shipment: dict[str, Any]) -> LabelResult:
        from app.services.delhivery import DelhiveryService
        response = await DelhiveryService().label(str(shipment.get("awb") or ""))
        return LabelResult(provider=self.provider, content=response.content, format=LabelFormat.PDF, content_type="application/pdf")


class ShadowfaxAdapter(CourierAdapter):
    provider = "shadowfax"
    capabilities = ProviderCapabilities(serviceability=True, booking=True, tracking=True, cancellation=True, labels=True, ndr=True, webhooks=False, polling=True)

    def __init__(self, *, token: str | None = None, base_url: str | None = None, transport: ShadowfaxTransport | None = None) -> None:
        self._token = token if token is not None else settings.shadowfax_effective_token
        self._base_url = (base_url if base_url is not None else settings.shadowfax_base_url or "").rstrip("/")
        if transport is None and self._token and self._base_url:
            from app.services.courier_platform.shadowfax_http import ShadowfaxHTTPTransport
            transport = ShadowfaxHTTPTransport(token=self._token, base_url=self._base_url)
        self._transport = transport

    @property
    def configured(self) -> bool:
        # Credentials alone must never advertise Shadowfax as operational while
        # the official Forward Integration HTTP transport remains unwired.
        return bool(self._token and self._base_url and self._transport is not None)

    def configuration_errors(self) -> list[str]:
        errors = []
        if not self._token: errors.append("SHADOWFAX_API_TOKEN is not configured (SHADOWFAX_TOKEN remains a legacy fallback).")
        if not self._base_url: errors.append("SHADOWFAX_BASE_URL is not configured.")
        if self._transport is None: errors.append("Shadowfax Direct transport is not configured.")
        return errors

    def _require_transport(self, operation: str) -> ShadowfaxTransport:
        errors = self.configuration_errors()
        if errors:
            raise ProviderConfigurationError(" ".join(errors), provider=self.provider, operation=operation)
        if self._transport is None:
            # TODO(official-shadowfax-spec): implement the bounded, no-POST-retry HTTP transport
            # using only documented endpoints, headers, fields and response contracts.
            raise ProviderConfigurationError(
                "Shadowfax Direct transport is not wired. Add the official Forward Integration endpoint contract.",
                provider=self.provider, operation=operation,
            )
        return self._transport

    async def authenticate(self) -> bool:
        # TODO(official-shadowfax-spec): wire the documented authentication/profile operation.
        return await self._require_transport("authenticate").authenticate()

    async def serviceability(self, request: dict[str, Any]) -> ServiceabilityResult:
        # TODO(official-shadowfax-spec): wire the documented serviceability operation.
        raw = await self._require_transport("serviceability").serviceability(request)
        serviceable = bool(raw.get("serviceable"))
        quote = QuoteResult(
            provider=self.provider, service_id=str(raw.get("service_id") or "shadowfax-direct"),
            courier_name=str(raw.get("courier_name") or "Shadowfax Direct"), serviceable=serviceable,
            charges=float(raw["charges"]) if raw.get("charges") is not None else None,
            estimated_delivery_days=int(raw["estimated_delivery_days"]) if raw.get("estimated_delivery_days") is not None else None,
            expected_delivery_date=str(raw.get("expected_delivery_date")) if raw.get("expected_delivery_date") else None,
            service_type=str(raw.get("service_type")) if raw.get("service_type") else None,
            reason=str(raw.get("reason")) if raw.get("reason") else None, raw_response=self.sanitize(raw),
        )
        return ServiceabilityResult(provider=self.provider, serviceable=serviceable, quotes=[quote] if serviceable else [], reason=quote.reason)

    def _booking(self, raw: dict[str, Any], *, existing: bool = False, reconciled: bool = False) -> BookingResult:
        awb = str(raw.get("awb") or "") or None
        provider_order_id = str(raw.get("provider_order_id") or "") or None
        shipment_id = str(raw.get("shipment_id") or "") or None
        if not (provider_order_id or shipment_id or awb):
            raise ProviderError("Shadowfax did not return a booking identifier.", provider=self.provider, operation="booking", uncertain=True)
        status = normalize_status(raw.get("status") or ("booked" if awb else "created"))
        return BookingResult(
            provider=self.provider, provider_order_id=provider_order_id, shipment_id=shipment_id, awb=awb,
            tracking_url=str(raw.get("tracking_url") or "") or None, service=str(raw.get("service") or "") or None,
            status=status, booked_at=datetime.now(timezone.utc), label_url=str(raw.get("label_url") or "") or None,
            label_format=LabelFormat(str(raw["label_format"]).casefold()) if raw.get("label_format") else None,
            confidence=BookingConfidence.RECONCILED if reconciled else BookingConfidence.CONFIRMED,
            reconciliation_status=ReconciliationStatus.CONFIRMED if reconciled else ReconciliationStatus.NOT_REQUIRED,
            existing=existing, raw_response=self.sanitize(raw),
        )

    async def create_booking(self, request: dict[str, Any]) -> BookingResult:
        # TODO(official-shadowfax-spec): wire the documented create-booking operation. Never retry this POST automatically.
        return self._booking(await self._require_transport("booking").create_booking(request))

    async def reconcile_booking(self, merchant_order_id: str) -> BookingResult | None:
        raw = await self._require_transport("reconciliation").find_booking(merchant_order_id)
        return self._booking(raw, existing=True, reconciled=True) if raw else None

    async def track_shipment(self, shipment: dict[str, Any]) -> TrackingResult:
        # TODO(official-shadowfax-spec): wire the documented tracking operation.
        raw = await self._require_transport("tracking").track_shipment(shipment)
        status = normalize_status(raw.get("status"))
        return TrackingResult(
            provider=self.provider, status=status, provider_status=str(raw.get("status") or "") or None,
            latest_scan=str(raw.get("latest_scan") or "") or None,
            latest_tracking_at=raw.get("timestamp") if isinstance(raw.get("timestamp"), datetime) else None,
            tracking_url=str(raw.get("tracking_url") or "") or None, terminal=is_terminal(status),
            ndr_reason=str(raw.get("ndr_reason") or "") or None,
            ndr_attempt=int(raw["ndr_attempt"]) if raw.get("ndr_attempt") is not None else None,
            courier_remarks=str(raw.get("remarks") or "") or None, raw_response=self.sanitize(raw),
        )

    async def cancel_booking(self, shipment: dict[str, Any]) -> CancellationResult:
        current = normalize_status(shipment.get("normalized_status") or shipment.get("latest_status"))
        if current == NormalizedShipmentStatus.CANCELLED:
            return CancellationResult(provider=self.provider, status="already_cancelled", cancelled=True, provider_status=current.value, message="Shipment is already cancelled.")
        if current in {NormalizedShipmentStatus.PICKED_UP, NormalizedShipmentStatus.IN_TRANSIT, NormalizedShipmentStatus.OUT_FOR_DELIVERY, NormalizedShipmentStatus.DELIVERED, NormalizedShipmentStatus.RTO}:
            raise ProviderError("A picked-up, shipped, delivered, or RTO shipment cannot use normal cancellation.", provider=self.provider, operation="cancellation")
        if shipment.get("booking_confidence") == BookingConfidence.UNCERTAIN:
            raise ProviderError("Reconcile the uncertain booking before cancellation.", provider=self.provider, operation="cancellation")
        # TODO(official-shadowfax-spec): wire the documented cancellation operation.
        raw = await self._require_transport("cancellation").cancel_booking(shipment)
        cancelled = bool(raw.get("cancelled"))
        return CancellationResult(provider=self.provider, status="cancelled" if cancelled else "rejected", cancelled=cancelled, provider_status=str(raw.get("status") or "") or None, message=str(raw.get("message") or ("Shipment cancelled." if cancelled else "Provider rejected cancellation.")), raw_response=self.sanitize(raw))

    async def download_label(self, shipment: dict[str, Any]) -> LabelResult:
        # TODO(official-shadowfax-spec): wire the documented label operation.
        content, content_type, source_url = await self._require_transport("label").download_label(shipment)
        mapping = {"application/pdf": LabelFormat.PDF, "image/png": LabelFormat.PNG, "image/jpeg": LabelFormat.JPEG}
        if content_type not in mapping:
            raise ProviderError("Shadowfax returned an unsupported label format.", provider=self.provider, operation="label")
        return LabelResult(provider=self.provider, content=content, format=mapping[content_type], content_type=content_type, source_url=source_url)
